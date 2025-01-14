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
from web3.logs import DISCARD

from bot.utils import fetch_abi, list_cogs, shift
from bot.bot import Bot


class BoardroomBot(Bot):
    contracts = {}
    config = {}
    nickname = ''
    epoch = ''
    next_epoch = ''
    epoch_price = None
    cash_per_share = None
    burnable_cash = None
    filter_lastblock = None

    def __init__(self, config, common, boardroom):
        super().__init__(config, common, None, list_cogs('commands', __file__))
        self.config = config
        self.boardroom = boardroom

        self.contracts['cash'] = self.web3.eth.contract(
            address=self.boardroom['cash'], abi=fetch_abi(boardroom['cash']))
        self.contracts['cash_lp'] = self.web3.eth.contract(
            address=self.boardroom['cash_lp'], abi=fetch_abi(boardroom['cash_lp']))
        self.contracts['share'] = self.web3.eth.contract(
            address=self.boardroom['share'], abi=fetch_abi(boardroom['share']))
        self.contracts['share_lp'] = self.web3.eth.contract(
            address=self.boardroom['share_lp'], abi=fetch_abi(boardroom['share_lp']))
        self.contracts['bond'] = self.web3.eth.contract(
            address=self.boardroom['bond'], abi=fetch_abi(boardroom['bond']))
        self.contracts['rewards'] = self.web3.eth.contract(
            address=self.boardroom['rewards'], abi=fetch_abi(boardroom['rewards']))
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
        if not self.boardroom.get('bond_decimals'):
            self.boardroom['bond_decimals'] = self.contracts['bond'].functions.decimals(
            ).call()

        # cache constants
        self.boardroom['treasury_gameFundSharedPercent'] = Decimal(
            self.contracts['treasury'].functions.gameFundSharedPercent().call())
        self.boardroom['treasury_PERIOD'] = self.contracts['treasury'].functions.PERIOD(
        ).call()
        self.boardroom['rewards_startBlock'] = self.contracts['rewards'].functions.startBlock(
        ).call()
        self.boardroom['rewards_TOTAL_REWARDS'] = shift(Decimal(self.contracts['rewards'].functions.TOTAL_REWARDS(
        ).call()), -self.boardroom['share_decimals'])

        self.filter_lastblock = self.web3.eth.block_number

    def get_epoch(self):
        self.epoch = self.contracts['treasury'].functions.epoch().call()
        epoch_time_delta = relativedelta(datetime.utcnow(),
                                         datetime.utcfromtimestamp(self.contracts['treasury'].functions.nextEpochPoint().call()))
        self.next_epoch = f"in {abs(epoch_time_delta.hours)}h {abs(epoch_time_delta.minutes)}m"

        self.epoch_price = shift(Decimal(self.contracts['treasury'].functions.getDollarPrice().call(
        )), -self.boardroom['cash_decimals'])
        self.total_cash_supply = shift(Decimal(self.contracts['cash'].functions.totalSupply().call(
        )) - Decimal(self.contracts['treasury'].functions.seigniorageSaved().call()), -self.boardroom['cash_decimals'])
        self.boardroom_stake = shift(Decimal(self.contracts['boardroom'].functions.totalSupply().call(
        )), -self.boardroom['share_decimals'])

        if self.epoch_price > Decimal(1):
            expansion_rate = min(self.epoch_price - Decimal(1), Decimal(
                self.contracts['treasury'].functions.maxSupplyExpansionPercent().call()) / Decimal(10000))
            seigniorage_amount = self.total_cash_supply * expansion_rate
            boardroom_amount = seigniorage_amount * \
                (Decimal(
                    1) - self.boardroom['treasury_gameFundSharedPercent'] / Decimal(10000))
            self.cash_per_share = boardroom_amount / self.boardroom_stake
            self.burnable_cash = None
        else:
            self.burnable_cash = shift(Decimal(self.contracts['treasury'].functions.getBurnableDollarLeft().call(
            )), -self.boardroom['cash_decimals'])
            self.cash_per_share = None

    def generate_presence(self):
        if self.burnable_cash is not None:
            return f"{self.burnable_cash:,.2f} SOUPB available"

        if not self.cash_per_share:
            return ''

        return f"{self.cash_per_share:.4f} SOUP per SOUPS"

    def generate_nickname(self):
        return f"Epoch {self.epoch+1} {self.next_epoch}"

    def generate_stats(self):
        self.get_bnb_price(self.amm['address'])

        # amounts in LPs
        (self.cash_lp_bnb_amount, self.cash_lp_token_amount) = self.get_lp_amounts(
            self.contracts['cash'], self.boardroom['cash_lp'], self.boardroom["cash_decimals"])
        self.cash_price = self.cash_lp_bnb_amount / self.cash_lp_token_amount
        (self.share_lp_bnb_amount, self.share_lp_token_amount) = self.get_lp_amounts(
            self.contracts['share'], self.boardroom['share_lp'], self.boardroom["share_decimals"])
        self.share_price = self.share_lp_bnb_amount / self.share_lp_token_amount

        # share supply = (totalSupply - total rewards) + unclaimed funds + generated rewards
        total_share_supply = shift(
            Decimal(self.contracts['share'].functions.totalSupply().call()) +
            Decimal(self.contracts['share'].functions.unclaimedTreasuryFund().call()) +
            Decimal(
                self.contracts['share'].functions.unclaimedDevFund().call()) +
            Decimal(
                self.contracts['rewards'].functions.getGeneratedReward(self.boardroom['rewards_startBlock'], self.filter_lastblock).call()), -self.boardroom['share_decimals']) - self.boardroom['rewards_TOTAL_REWARDS']

        # LPs staked in rewards
        total_cash_lp_supply = shift(Decimal(
            self.contracts['cash_lp'].functions.totalSupply().call()), -18)
        rewards_cash_lp = shift(Decimal(self.contracts['cash_lp'].functions.balanceOf(
            self.boardroom['rewards']).call()), -18)
        rewards_cash_lp_pct = rewards_cash_lp / total_cash_lp_supply
        rewards_cash_lp_value = (
            self.cash_lp_token_amount * self.cash_price + self.cash_lp_bnb_amount) * rewards_cash_lp_pct

        total_share_lp_supply = shift(Decimal(
            self.contracts['share_lp'].functions.totalSupply().call()), -18)
        rewards_share_lp = shift(Decimal(self.contracts['share_lp'].functions.balanceOf(
            self.boardroom['rewards']).call()), -18)
        rewards_share_lp_pct = rewards_share_lp / total_share_lp_supply
        rewards_share_lp_value = (
            self.share_lp_token_amount * self.share_price + self.share_lp_bnb_amount) * rewards_share_lp_pct

        # bonds
        total_bond_supply = shift(
            Decimal(self.contracts['bond'].functions.totalSupply().call()), -self.boardroom['bond_decimals'])
        debt_ratio = total_bond_supply / self.total_cash_supply

        cash_mc = self.total_cash_supply * self.cash_price
        share_mc = total_share_supply * self.share_price
        tvl = self.boardroom_stake * self.share_price + \
            rewards_share_lp_value + rewards_cash_lp_value

        expansion_or_contraction_stats = ''
        if self.epoch_price > Decimal(1):
            roi = self.cash_per_share * self.cash_price / self.share_price
            epochs_per_day = Decimal(86400) / self.boardroom['treasury_PERIOD']
            expansion_or_contraction_stats = f"Est. Boiler ROI:     {roi:.2%} per epoch, {roi*epochs_per_day:.2%} daily"
        else:

            expansion_or_contraction_stats = f"SoupB Available:     {self.burnable_cash:,.2f}"

        # get busd value of all cash, shares (incl. rewards), LPs
        def get_all_balance(address):
            cash = shift(Decimal(self.contracts['cash'].functions.balanceOf(
                address).call()), -self.boardroom['cash_decimals'])
            share = shift(Decimal(self.contracts['share'].functions.balanceOf(
                address).call()), -self.boardroom['share_decimals'])
            cash_lp = shift(
                Decimal(self.contracts['cash_lp'].functions.balanceOf(address).call()), -18)
            share_lp = shift(
                Decimal(self.contracts['share_lp'].functions.balanceOf(address).call()), -18)

            cash_lp_staked = shift(Decimal(self.contracts['rewards'].functions.balanceOf(
                0, address).call()), -18)
            cash_lp_total_bnb = self.cash_lp_bnb_amount * 2 / \
                total_cash_lp_supply * (cash_lp + cash_lp_staked)
            cash_lp_rewards = shift(
                Decimal(self.contracts['rewards'].functions.pendingRewards(
                    0, address).call()), -self.boardroom['share_decimals'])

            share_lp_staked = shift(Decimal(self.contracts['rewards'].functions.balanceOf(
                1, address).call()), -18)
            share_lp_total_bnb = self.share_lp_bnb_amount * 2 / \
                total_share_lp_supply * (share_lp + share_lp_staked)
            share_lp_rewards = shift(
                Decimal(self.contracts['rewards'].functions.pendingRewards(
                    1, address).call()), -self.boardroom['share_decimals'])

            cash_total_bnb = cash * self.cash_price
            share_total_bnb = (share + cash_lp_rewards +
                               share_lp_rewards) * self.share_price
            return self.bnb_price * (cash_total_bnb + share_total_bnb + cash_lp_total_bnb + share_lp_total_bnb)

        game_fund = get_all_balance(self.boardroom['game_fund'])
        community_fund = get_all_balance(self.boardroom['community_fund'])
        dev_fund = get_all_balance(self.boardroom['dev_fund'])

        description = f""":notepad_spiral: **The Latest Soup** :notepad_spiral:
```
Total Soup:          {self.total_cash_supply:,.2f}
Soup Price:          {self.cash_price:.2f} BNB (${(self.cash_price * self.bnb_price):,.2f})
Soup Market Cap:     {cash_mc:,.2f} BNB (${(cash_mc * self.bnb_price):,.0f})

Total Soups:         {total_share_supply:,.2f}
Soups Price:         {self.share_price:,.2f} BNB (${(self.share_price * self.bnb_price):,.2f})
Soups Market Cap:    {share_mc:,.2f} BNB (${(share_mc * self.bnb_price):,.0f})
Soups in LP:         {self.share_lp_token_amount:,.2f} ({self.share_lp_token_amount/total_share_supply:.2%})
Soups in Boiler:     {self.boardroom_stake:,.2f} ({self.boardroom_stake/total_share_supply:.2%})

Soup LP in Kitchen:  ${(rewards_cash_lp_value * self.bnb_price):,.0f} ({rewards_cash_lp_pct:.2%})
Soups LP in Kitchen: ${(rewards_share_lp_value * self.bnb_price):,.0f} ({rewards_share_lp_pct:.2%})
TVL:                 ${tvl * self.bnb_price:,.0f}

Total Soup Bonds:    {total_bond_supply:,.2f} ({debt_ratio:.2%})

Soups/Soup Ratio:    {self.share_price/self.cash_price:.2f}
TWAP:                {self.epoch_price:.2f}
{expansion_or_contraction_stats}

Game Fund:           ${game_fund:,.0f}
Community Fund:      ${community_fund:,.0f}
Dev Fund:            ${dev_fund:,.0f}
```"""
        return description

    async def get_latest_events(self):
        to_block = self.web3.eth.block_number
        print('from', self.filter_lastblock, 'to', to_block)

        method_id = self.web3.keccak(text="allocateSeigniorage()")[0:4].hex()

        timestamp, title, description = None, None, None
        for block_number in range(self.filter_lastblock, to_block):
            block = self.web3.eth.get_block(
                block_number, full_transactions=True)
            for tx in block.transactions:
                if tx.to == self.boardroom['treasury'] and tx.input == method_id:
                    receipt = self.web3.eth.getTransactionReceipt(tx.hash)
                    seigniorage_event = self.contracts['treasury'].events.BoilerFunded(
                    ).processReceipt(receipt, errors=DISCARD)
                    print(receipt)

                    self.get_epoch()  # refresh epoch data

                    if seigniorage_event:
                        timestamp = datetime.utcfromtimestamp(
                            seigniorage_event[0].args.timestamp)
                        seigniorage = shift(Decimal(
                            seigniorage_event[0].args.seigniorage), -self.boardroom['cash_decimals'])

                        title = ':fondue::fondue::fondue: **Soup has been served!** :fondue::fondue::fondue:'
                        description = f"""```
Epoch {self.epoch}
Fresh hot Soup: {seigniorage:.2f}
Soup per Soups: {(seigniorage / self.boardroom_stake):.4f}
```
{self.generate_stats()}
"""
                    else:
                        timestamp = datetime.utcfromtimestamp(
                            block.timestamp)

                        title = '**No Soup has been served**'
                        description = f"""```
Epoch {self.epoch}
```
{self.generate_stats()}
"""
                    break

        self.filter_lastblock = to_block + 1

        if timestamp:
            embed = discord.Embed(color=discord.Color.green(),
                                  title=title, description=description, timestamp=timestamp)

            for channel_id in self.boardroom['stats_channels']:
                channel = self.get_channel(channel_id)
                if channel:
                    await channel.send(embed=embed)
