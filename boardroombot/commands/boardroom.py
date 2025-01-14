import math
from datetime import datetime

import discord
from discord.ext import tasks, commands
from decimal import Decimal, DecimalException
from web3 import Web3


class Boardroom(commands.Cog, command_attrs=dict(hidden=True)):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        await self.update()

        self.bot.epoch_loop = tasks.loop(
            seconds=self.bot.config['refresh_rate'])(self.update)
        self.bot.epoch_loop.add_exception_type(discord.errors.HTTPException)
        self.bot.epoch_loop.add_exception_type(ValueError)
        self.bot.epoch_loop.start()

        if 'stats_channels' in self.bot.boardroom:
            refresh_rate = self.bot.common.get(
                'refresh_rate', self.bot.config['refresh_rate'])
            self.bot.events_loop = tasks.loop(
                seconds=refresh_rate)(self.bot.get_latest_events)
            self.bot.events_loop.add_exception_type(
                discord.errors.HTTPException)
            self.bot.events_loop.add_exception_type(ValueError)
            self.bot.events_loop.start()

    async def update(self):
        self.bot.get_epoch()

        for guild in self.bot.guilds:
            await guild.me.edit(nick=self.bot.generate_nickname())

        presence = self.bot.generate_presence()
        if presence:
            await self.bot.change_presence(activity=discord.Game(name=presence))

    @commands.command(help='Display statistics')
    async def stats(self, ctx: commands.Context):
        async with ctx.typing():
            stats = self.bot.generate_stats()
            await ctx.channel.send(stats)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound) or isinstance(error, commands.CheckFailure):
            pass
        else:
            raise error

    async def cog_check(self, ctx: commands.Context):
        if isinstance(ctx.channel, discord.channel.DMChannel):
            return True
        return await self.bot.check_restrictions(ctx)


def setup(bot: commands.Bot):
    bot.add_cog(Boardroom(bot))
