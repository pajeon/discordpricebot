import json
import os
from decimal import Decimal, DecimalException
from urllib.parse import urlparse
from itertools import chain

import discord
from discord.ext import tasks, commands
from urllib.request import urlopen, Request
from web3 import Web3

from bot.utils import list_cogs


class Bot(commands.Bot):
    commands = []
    config = {}
    nickname = ''

    intents = discord.Intents.default()
    intents.members = True

    def __init__(self, config, bot_config, extra_cogs=[]):
        super().__init__(command_prefix=self.handle_prefix, case_insensitive=True)
        self.commands = chain(list_cogs('commands'), extra_cogs)
        self.config = config
        self.bot_config = bot_config

        if node := config.get('bsc_node'):
            bsc_node = urlparse(node)
            if 'http' in bsc_node.scheme:
                provider = Web3.HTTPProvider(node)
            else:
                provider = Web3.IPCProvider(bsc_node.path)

            self.web3 = Web3(provider)  # type: Web3.eth.account
        else:
            raise Exception("Required setting 'bsc_node' not configured!")

        self.help_command = commands.DefaultHelpCommand(
            command_attrs={"hidden": True})

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
                if self.bot_config.get('command_override'):
                    override = self.bot_config.get('command_override')
                    cog = override.get(cog, cog)

                self.load_extension(cog)
            except Exception as e:
                print(f'Failed to load extension {cog}.', e)

        self.run(self.bot_config['apikey'])
