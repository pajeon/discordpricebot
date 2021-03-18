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
    price_bnb = 0
    price_busd = 0
    bnb_amount = 0
    token_amount = 0
    total_supply = 0
    display_precision = Decimal('0.0001')  # Round to 4 token_decimals

    def __init__(self, config, common, token):
        super().__init__(config, common, list_cogs('commands', __file__))
        self.config = config
        self.common = common
        self.token = token

        self.contracts['token'] = self.web3.eth.contract(
            address=self.token['contract'], abi=self.token_abi)
        self.contracts['lp'] = self.web3.eth.contract(
            address=self.token['lp'], abi=fetch_abi(self.token['lp']))

        if not self.token.get('decimals'):
            self.token['decimals'] = self.contracts['token'].functions.decimals().call()

        self.dbengine = create_engine('sqlite:///pricebot.db', echo=True)
        session = sessionmaker(bind=self.dbengine)
        self.db = session()

    def icon_value(self, value=None):
        if self.token['emoji'] or self.token['icon']:
            value = f" {value}" if value else ''
            return f"{self.token['emoji'] or self.token['icon']}{value}"

        value = f"{value} " if value else ''
        return f"{value}{self.common['name']}"

    def get_token_price(self):
        prices = self.get_prices(self.contracts['token'], self.token['lp'],
                                 self.amm['address'], self.token["decimals"])
        self.bnb_amount = prices['bnb_amount']
        self.token_amount = prices['token_amount']
        self.price_bnb = prices['price_bnb']
        self.price_busd = prices['price_busd']
        return prices['price_busd']

    def generate_presence(self):
        if not self.token_amount:
            return ''

        try:
            total_supply = shift(Decimal(self.contracts['lp'].functions.totalSupply(
            ).call()), -18)
            values = [Decimal(self.token_amount / total_supply),
                      Decimal(self.bnb_amount / total_supply)]
            lp_price = self.price_busd * values[0] * 2

            return f"LP ≈${round(lp_price, 2)} | {round(values[0], 4)} {self.token['icon']} + {round(values[1], 4)} BNB"
        except ValueError:
            pass

    def generate_nickname(self):
        return f"{self.price_bnb:.2f} BNB (${self.price_busd:.2f})"

    async def get_lp_value(self):
        self.total_supply = shift(Decimal(self.contracts['lp'].functions.totalSupply(
        ).call()), -18)
        return [self.token_amount / self.total_supply, self.bnb_amount / self.total_supply]
