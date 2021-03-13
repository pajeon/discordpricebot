import json
import os
from datetime import datetime
from dateutil.relativedelta import relativedelta
from decimal import Decimal, DecimalException
from urllib.parse import urlparse

import discord
from discord.ext import tasks, commands
from urllib.request import urlopen, Request
from web3 import Web3

from bot.utils import fetch_abi, list_cogs
from bot.bot import Bot


class BoardroomBot(Bot):
    contracts = {}
    config = {}
    nickname = ''
    epoch = ''
    next_epoch = ''
    cash_per_share = None

    def __init__(self, config, bot, boardroom):
        super().__init__(config, bot, list_cogs('commands', __file__))
        self.config = config
        self.bot = bot
        self.boardroom = boardroom

        self.contracts['cash'] = self.web3.eth.contract(
            address=self.boardroom['cash'], abi=fetch_abi(boardroom['cash']))
        self.contracts['share'] = self.web3.eth.contract(
            address=self.boardroom['share'], abi=fetch_abi(boardroom['share']))
        self.contracts['treasury'] = self.web3.eth.contract(
            address=self.boardroom['treasury'], abi=fetch_abi(boardroom['treasury']))
        self.contracts['boardroom'] = self.web3.eth.contract(
            address=self.boardroom['boardroom'], abi=fetch_abi(boardroom['boardroom']))

        if not self.boardroom.get('cash_decimals'):
            self.boardroom['cash_decimals'] = self.contracts['cash'].functions.decimals(
            ).call()
        if not self.boardroom.get('share_decimals'):
            self.boardroom['share_decimals'] = self.contracts['share'].functions.decimals(
            ).call()

    def get_epoch(self):
        self.epoch = self.contracts['treasury'].functions.epoch().call()
        epoch_time_delta = relativedelta(datetime.utcnow(),
                                         datetime.utcfromtimestamp(self.contracts['treasury'].functions.nextEpochPoint().call()))
        self.next_epoch = f"in {abs(epoch_time_delta.hours)}h {abs(epoch_time_delta.minutes)}m"

        epoch_price = Decimal(self.contracts['treasury'].functions.getDollarPrice().call(
        )) * Decimal(10**(-self.boardroom['cash_decimals']))
        if epoch_price > Decimal(1):
            expansion_rate = min(epoch_price - Decimal(1), Decimal(
                self.contracts['treasury'].functions.maxSupplyExpansionPercent().call()) / Decimal(10000))
            total_cash_supply = (Decimal(self.contracts['cash'].functions.totalSupply().call(
            )) - Decimal(self.contracts['treasury'].functions.seigniorageSaved().call())) * Decimal(10**(-self.boardroom['cash_decimals']))
            new_supply = total_cash_supply * expansion_rate
            boardroom_stake = Decimal(self.contracts['boardroom'].functions.totalSupply().call(
            )) * Decimal(10**(-self.boardroom['share_decimals']))
            self.cash_per_share = new_supply / boardroom_stake

        else:
            self.cash_per_share = None

    def generate_presence(self):
        if not self.cash_per_share:
            return 'No expansion'

        return f"{round(self.cash_per_share, 4):.4f} SOUP per SOUPS"

    def generate_nickname(self):
        return f"Epoch {self.epoch} {self.next_epoch}"
