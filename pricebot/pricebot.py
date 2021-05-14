import json
import os
from decimal import Decimal, DecimalException
from urllib.parse import urlparse

import discord
from discord.ext import tasks
from urllib.request import urlopen, Request
from web3 import Web3
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from bot.utils import fetch_abi, list_cogs, shift
from bot.bot import Bot


class PriceBot(Bot):
    price_quote = 0
    price_busd = 0
    quote_amount = 0
    token_amount = 0
    total_supply = 0

    def __init__(self, config, common, token):
        super().__init__(config, common, token, list_cogs('commands', __file__))
        self.config = config
        self.common = common

        self.contracts['token'] = self.web3.eth.contract(
            address=self.token['contract'], abi=self.token_abi)
        self.contracts['lp'] = self.web3.eth.contract(
            address=self.token['lp'], abi=fetch_abi(self.token['lp']))

        if not self.token.get('decimals'):
            self.token['decimals'] = self.contracts['token'].functions.decimals().call()

        self.dbengine = create_engine('sqlite:///pricebot.db', echo=True)
        session = sessionmaker(bind=self.dbengine)
        self.db = session()
        self.get_token_price()

    def icon_value(self, value=None):
        if self.token['emoji'] or self.token['icon']:
            value = f" {value}" if value else ''
            return f"{self.token['emoji'] or self.token['icon']}{value}"

        value = f"{value} " if value else ''
        return f"{value}{self.common['name']}"

    def get_token_price(self):
        if self.amm.get('stableswap'):
            self.price_busd = shift(Decimal(
                self.contracts['lp'].functions.calculateSwapToBase(
                    self.token['pool'],
                    self.token['basePool'],
                    self.token['fromIndex'],
                    self.token['toIndex'],
                    10 ** self.token['decimals']
                ).call()), -self.token['decimals'])
            return self.price_busd

        prices = self.get_prices(self.contracts['token'], self.token['lp'],
                                 self.amm['address'], self.token["decimals"])
        self.quote_amount = prices['quote_amount']
        self.token_amount = prices['token_amount']
        self.price_quote = prices['price_quote']
        self.price_busd = prices['price_busd']
        return prices['price_busd']

    def generate_presence(self):
        if self.token.get('show_mc'):
            total_supply = shift(
                Decimal(self.contracts['token'].functions.totalSupply().call()), -18)
            mc = self.price_busd * total_supply
            return f"MC=${mc:,.0f}"

        elif not self.token.get('show_lp', True) or self.amm.get('stableswap'):
            return ''

        if not self.token_amount:
            return ''

        try:
            total_supply = shift(Decimal(self.contracts['lp'].functions.totalSupply(
            ).call()), -18)
            values = [Decimal(self.token_amount / total_supply),
                      Decimal(self.quote_amount / total_supply)]
            lp_price = self.price_busd * values[0] * 2

            return f"LP ≈${round(lp_price, 2)} | {round(values[0], 4)} {self.token['icon']} + {round(values[1], 4)} BNB"
        except ValueError:
            pass

    def generate_nickname(self):
        price_busd = round(
            self.price_busd, self.token.get('display_decimals', 2))

        if self.token['contract'] == self.address['bnb']:
            return f"${price_busd:,f}"

        if self.token.get('show_bnb_price', True):
            if self.token.get('display') == 'bnb':
                return f"{self.price_quote:.2f} BNB (${price_busd:,f})"
            return f"${price_busd:,f} ({self.price_quote:.2f} BNB)"
        else:
            return f"${price_busd:,f}"

    async def get_lp_value(self):
        self.total_supply = shift(Decimal(self.contracts['lp'].functions.totalSupply(
        ).call()), -18)
        return [self.token_amount / self.total_supply, self.quote_amount / self.total_supply]
