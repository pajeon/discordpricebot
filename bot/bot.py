import json
import os
from decimal import Decimal, DecimalException
from urllib.parse import urlparse
from itertools import chain

import discord
from discord.ext import tasks, commands
from urllib.request import urlopen, Request
from web3 import Web3
from web3.middleware import geth_poa_middleware

from bot.utils import fetch_abi, list_cogs, shift


class Bot(commands.Bot):
    commands = []
    contracts = {}
    config = {}
    nickname = ''
    bnb_price = 0
    token_abi = []

    # Static BSC contract addresses
    address = {
        'bnb': '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c',
        'busd': '0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56'
    }

    intents = discord.Intents.default()
    intents.members = True

    def __init__(self, config, common, extra_cogs=[]):
        super().__init__(command_prefix=self.handle_prefix, case_insensitive=True)
        self.commands = chain(list_cogs('commands'), extra_cogs)
        self.config = config
        self.common = common
        self.amm = config['amm'][common['amm']]

        if not config['amm'].get(common['amm']):
            raise Exception(
                f"{common['name']}'s AMM {common['amm']} does not exist!")

        if node := config.get('bsc_node'):
            bsc_node = urlparse(node)
            if 'http' in bsc_node.scheme:
                provider = Web3.HTTPProvider(node)
            else:
                provider = Web3.IPCProvider(bsc_node.path)

            self.web3 = Web3(provider)  # type: Web3.eth.account
            self.web3.middleware_onion.inject(geth_poa_middleware, layer=0)
        else:
            raise Exception("Required setting 'bsc_node' not configured!")

        self.token_abi = fetch_abi(self.address['bnb'])
        self.contracts['bnb'] = self.web3.eth.contract(
            address=self.address['bnb'], abi=self.token_abi)
        self.contracts['busd'] = self.web3.eth.contract(
            address=self.address['busd'], abi=self.token_abi)

        self.help_command = commands.DefaultHelpCommand(
            command_attrs={"hidden": True})

    def get_amm(self, amm=None):
        if not amm:
            return self.amm

        return self.config['amm'].get(amm)

    def get_bnb_price(self, lp):
        bnb_amount = Decimal(
            self.contracts['bnb'].functions.balanceOf(lp).call())
        busd_amount = Decimal(
            self.contracts['busd'].functions.balanceOf(lp).call())

        self.bnb_price = Decimal(busd_amount) / Decimal(bnb_amount)

        return self.bnb_price

    def get_lp_amounts(self, token_contract, native_lp, decimals):
        bnb_amount = shift(Decimal(
            self.contracts['bnb'].functions.balanceOf(native_lp).call()), -18)
        token_amount = shift(Decimal(token_contract.functions.balanceOf(native_lp).call(
        )), -decimals)
        return (bnb_amount, token_amount)

    def get_prices(self, token_contract, native_lp, bnb_lp, decimals):
        (bnb_amount, token_amount) = self.get_lp_amounts(
            token_contract, native_lp, decimals)

        try:
            price_bnb = bnb_amount / token_amount
        except ZeroDivisionError:
            price_bnb = 0

        bnb_price = self.get_bnb_price(bnb_lp)
        price_busd = price_bnb * bnb_price
        return {
            'bnb_amount': bnb_amount,
            'token_amount': token_amount,
            'price_bnb': price_bnb,
            'price_busd': price_busd
        }

    def handle_prefix(self, bot, message):
        if isinstance(message.channel, discord.channel.DMChannel):
            return ''

        return commands.when_mentioned(bot, message)

    def generate_presence():
        pass

    def generate_nickname():
        pass

    async def on_guild_join(self, guild):
        await guild.me.edit(nick=self.nickname)

    async def check_restrictions(self, ctx):
        server_restriction = self.config.get(
            'restrict_to', {}).get(ctx.guild.id)
        if server_restriction and not await self.is_owner(ctx.author):
            if ctx.channel.id not in server_restriction:
                if ctx.channel.permissions_for(ctx.guild.me).manage_messages:
                    await ctx.message.delete()
                return False
        return True

    async def on_ready(self):
        restrictions = self.config.get('restrict_to', {})
        all_channels = self.get_all_channels()
        for guild_id, channels in restrictions.items():
            for i, channel in enumerate(channels):
                if not self.parse_int(channel):
                    channels[i] = discord.utils.get(
                        all_channels, guild__id=guild_id, name=channel)
                    if not channels[i]:
                        raise Exception('No channel named channel!')

    @staticmethod
    def parse_int(val):
        try:
            val = int(val)
        except ValueError:
            val = None

        return val

    @staticmethod
    def parse_decimal(val):
        try:
            val = Decimal(val)
        except (TypeError, DecimalException):
            val = None

        return val

    def exec(self):
        for cog in self.commands:
            try:
                if self.common.get('command_override'):
                    override = self.common.get('command_override')
                    cog = override.get(cog, cog)

                self.load_extension(cog)
            except Exception as e:
                print(f'Failed to load extension {cog}.', e)

        self.run(self.common['apikey'])
