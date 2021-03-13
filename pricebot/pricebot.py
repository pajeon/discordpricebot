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

from bot.utils import fetch_abi, list_cogs
from bot.bot import Bot


class PriceBot(Bot):
    contracts = {}
    config = {}
    current_price = 0
    nickname = ''
    bnb_amount = 0
    bnb_price = 0
    token_amount = 0
    total_supply = 0
    display_precision = Decimal('0.0001')  # Round to 4 token_decimals

    # Static BSC contract addresses
    address = {
        'bnb': '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c',
        'busd': '0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56'
    }

    intents = discord.Intents.default()
    intents.members = True

    def __init__(self, config, bot, token):
        super().__init__(config, bot, list_cogs('commands', __file__))
        self.config = config
        self.bot = bot
        self.token = token
        self.amm = config['amm'][token['from']]

        if not config['amm'].get(token['from']):
            raise Exception(
                f"{bot['name']}'s AMM {token['from']} does not exist!")

        self.contracts['bnb'] = self.web3.eth.contract(
            address=self.address['bnb'], abi=self.token['abi'])
        self.contracts['busd'] = self.web3.eth.contract(
            address=self.address['busd'], abi=self.token['abi'])
        self.contracts['token'] = self.web3.eth.contract(
            address=self.token['contract'], abi=self.token['abi'])
        self.contracts['lp'] = self.web3.eth.contract(
            address=self.token['lp'], abi=fetch_abi(self.token['lp']))

        if not self.token.get('decimals'):
            self.token['decimals'] = self.contracts['token'].functions.decimals().call()

        self.dbengine = create_engine('sqlite:///pricebot.db', echo=True)
        session = sessionmaker(bind=self.dbengine)
        self.db = session()

    def get_amm(self, amm=None):
        if not amm:
            return self.amm

        return self.config['amm'].get(amm)

    def icon_value(self, value=None):
        if self.token['emoji'] or self.token['icon']:
            value = f" {value}" if value else ''
            return f"{self.token['emoji'] or self.token['icon']}{value}"

        value = f"{value} " if value else ''
        return f"{value}{self.bot['name']}"

    def get_bnb_price(self, lp):
        bnb_amount = Decimal(
            self.contracts['bnb'].functions.balanceOf(lp).call())
        busd_amount = Decimal(
            self.contracts['busd'].functions.balanceOf(lp).call())

        self.bnb_price = Decimal(busd_amount) / Decimal(bnb_amount)

        return self.bnb_price

    def get_price(self, token_contract, native_lp, bnb_lp):
        self.bnb_amount = Decimal(
            self.contracts['bnb'].functions.balanceOf(native_lp).call())
        self.token_amount = Decimal(token_contract.functions.balanceOf(native_lp).call(
        )) * Decimal(10 ** (18 - self.token["decimals"]))  # Normalize token_decimals

        bnb_price = self.get_bnb_price(bnb_lp)

        try:
            final_price = self.bnb_amount / self.token_amount * bnb_price
        except ZeroDivisionError:
            final_price = 0

        return final_price

    def get_token_price(self):
        return self.get_price(self.contracts['token'], self.token['lp'], self.amm['address']).quantize(self.display_precision)

    def generate_presence(self):
        if not self.token_amount:
            return ''

        try:
            total_supply = self.contracts['lp'].functions.totalSupply().call()
            values = [Decimal(self.token_amount / total_supply),
                      Decimal(self.bnb_amount / total_supply)]
            lp_price = self.current_price * values[0] * 2

            return f"LP ≈${round(lp_price, 2)} | {round(values[0], 4)} {self.token['icon']} + {round(values[1], 4)} BNB"
        except ValueError:
            pass

    def generate_nickname(self):
        return f"{round(self.bnb_amount / self.token_amount, 2):.2f} BNB (${self.current_price:.2f})"

    async def get_lp_value(self):
        self.total_supply = self.contracts['lp'].functions.totalSupply().call()
        return [self.token_amount / self.total_supply, self.bnb_amount / self.total_supply]
