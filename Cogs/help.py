import difflib
from asyncio import TimeoutError
from collections import Counter
from datetime import datetime, timedelta, timezone
from itertools import islice
from platform import python_version
from re import split

import discord
import pygit2
from discord.ext import commands
from humanize import naturalsize
from psutil import virtual_memory, cpu_percent, Process

from Utils.time import human_timedelta


class HelpCommand(commands.HelpCommand):
    """The custom help command class for the bot"""

    def __init__(self):
        super().__init__(verify_checks=True, command_attrs={
            'help': 'Shows help about the bot, a command, or a cog',
            'cooldown': commands.Cooldown(1, 3.0, commands.BucketType.member),
        })

    def get_command_signature(self, command) -> str:
        """Method to return a commands name and signature"""
        if not command.signature and not command.parent:  # checking if it has no args and isn't a subcommand
            return f'`{self.clean_prefix}{command.name}`'
        if command.signature and not command.parent:  # checking if it has args and isn't a subcommand
            sig = '` `'.join(split(r'\B ', command.signature))
            return f'`{self.clean_prefix}{command.name}` `{sig}`'
        if not command.signature and command.parent:  # checking if it has no args and is a subcommand
            return f'`{command.name}`'
        else:  # else assume it has args a signature and is a subcommand
            return '`{}` `{}`'.format(command.name, '`, `'.join(split(r'\B ', command.signature)))

    def get_command_aliases(self, command) -> str:
        """Method to return a commands aliases"""
        if not command.aliases:  # check if it has any aliases
            return ''
        else:
            return f'command aliases are [`{"` | `".join(command.aliases)}`]'

    def get_command_description(self, command) -> str:
        """Method to return a commands short doc/brief"""
        if not command.short_doc:  # check if it has any brief
            return 'There is no documentation for this command currently'
        else:
            return command.short_doc.format(prefix=self.clean_prefix)

    def get_command_help(self, command) -> str:
        """Method to return a commands full description/doc string"""
        if not command.help:  # check if it has any brief or doc string
            return 'There is currently no documentation for this command'
        else:
            return command.help.format(prefix=self.clean_prefix)

    async def send_bot_help(self, mapping):
        ctx = self.context
        bot = ctx.bot
        page = 0
        cogs = [name for name, obj in bot.cogs.items() if await discord.utils.maybe_coroutine(obj.cog_check, ctx)]
        cogs.sort()

        def check(reaction, user):  # check who is reacting to the message
            return user == ctx.author and help_embed.id == reaction.message.id
        embed = await self.bot_help_paginator(page, cogs)

        help_embed = await ctx.send(embed=embed)  # sends the first help page
        bot.loop.create_task(self.bot_help_paginator_reactor(help_embed))
        # this allows the bot to carry on setting up the help command

        while 1:
            try:
                reaction, user = await bot.wait_for('reaction_add', timeout=90, check=check)  # checks message reactions
            except TimeoutError:  # session has timed out
                try:
                    await help_embed.clear_reactions()
                except discord.errors.Forbidden:
                    pass
                break
            else:
                try:
                    await help_embed.remove_reaction(str(reaction.emoji), ctx.author)  # remove the reaction
                except discord.errors.Forbidden:
                    pass

                if str(reaction.emoji) == '⏭':  # go to the last the page
                    page = len(cogs) - 1
                    embed = await self.bot_help_paginator(page, cogs)
                    await help_embed.edit(embed=embed)
                elif str(reaction.emoji) == '⏮':  # go to the first page
                    page = 0
                    embed = await self.bot_help_paginator(page, cogs)
                    await ctx.send(len(embed))

                    await help_embed.edit(embed=embed)

                elif str(reaction.emoji) == '◀':  # go to the previous page
                    page -= 1
                    if page == -1:  # check whether to go to the final page
                        page = len(cogs) - 1
                    embed = await self.bot_help_paginator(page, cogs)
                    await help_embed.edit(embed=embed)
                elif str(reaction.emoji) == '▶':  # go to the next page
                    page += 1
                    if page == len(cogs):  # check whether to go to the first page
                        page = 0
                    embed = await self.bot_help_paginator(page, cogs)
                    await help_embed.edit(embed=embed)

                elif str(reaction.emoji) == 'ℹ':  # show information help
                    embed = discord.Embed(title=f'Help with {bot.user.name}\'s commands', description=bot.description,
                                          color=discord.Colour.blurple())
                    embed.add_field(
                        name=f'Currently there are {len(cogs)} cogs loaded, which includes (`{"`, `".join(cogs)}`) :gear:',
                        value='`<...>` indicates a required argument,\n`[...]` indicates an optional argument.\n\n'
                              '**Don\'t however type these around your argument**')
                    embed.add_field(name='What do the emojis do:',
                                    value=':track_previous: Goes to the first page\n'
                                          ':track_next: Goes to the last page\n'
                                          ':arrow_backward: Goes to the previous page\n'
                                          ':arrow_forward: Goes to the next page\n'
                                          ':stop_button: Deletes and closes this message\n'
                                          ':information_source: Shows this message')
                    embed.set_author(name=f'You were on page {page + 1}/{len(cogs)} before',
                                     icon_url=ctx.author.avatar_url)
                    embed.set_footer(text=f'Use "{self.clean_prefix}help <command>" for more info on a command.',
                                     icon_url=ctx.bot.user.avatar_url)
                    await help_embed.edit(embed=embed)

                elif str(reaction.emoji) == '⏹':  # delete the message and break from the wait_for
                    await help_embed.delete()
                    break

    async def bot_help_paginator_reactor(self, message):
        reactions = (
            '\N{BLACK LEFT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}',
            '\N{BLACK LEFT-POINTING TRIANGLE}',
            '\N{BLACK RIGHT-POINTING TRIANGLE}',
            '\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}',
            '\N{BLACK SQUARE FOR STOP}',
            '\N{INFORMATION SOURCE}'
        )  # add reactions to the message
        for reaction in reactions:
            await message.add_reaction(reaction)

    async def bot_help_paginator(self, page: int, cogs) -> discord.Embed:
        ctx = self.context
        bot = ctx.bot
        all_commands = [command for command in
                        await self.filter_commands(bot.commands)]  # filter the commands the user can use
        cog = bot.get_cog(cogs[page])  # get the current cog

        embed = discord.Embed(title=f'Help with {cog.qualified_name} ({len(all_commands)} commands)',
                              description=cog.description,
                              color=bot.config_cache[ctx.guild.id]['colour'] if ctx.guild else discord.Colour.blurple())
        embed.set_author(name=f'We are currently on page {page + 1}/{len(cogs)}', icon_url=ctx.author.avatar_url)
        for c in cog.walk_commands():
            try:
                if await c.can_run(ctx) and not c.hidden:
                    signature = self.get_command_signature(c)
                    description = self.get_command_description(c)
                    if c.parent:  # it is a sub-command
                        embed.add_field(name=f'**╚╡**{signature}', value=description)
                    else:
                        embed.add_field(name=signature, value=description, inline=False)
            except commands.CommandError:
                pass
        embed.set_footer(text=f'Use "{self.clean_prefix}help <command>" for more info on a command.',
                         icon_url=ctx.bot.user.avatar_url)
        return embed

    async def send_cog_help(self, cog):
        ctx = self.context
        cog_commands = [command for command in await self.filter_commands(cog.walk_commands())]  # get commands

        embed = discord.Embed(title=f'Help with {cog.qualified_name} ({len(cog_commands)} commands)',
                              description=cog.description,
                              color=ctx.bot.config_cache[ctx.guild.id][
                                  'colour'] if ctx.guild else discord.Colour.blurple())
        embed.set_author(name=f'We are currently looking at the module {cog.qualified_name} and its commands',
                         icon_url=ctx.author.avatar_url)
        for c in cog_commands:
            signature = self.get_command_signature(c)
            aliases = self.get_command_aliases(c)
            description = self.get_command_description(c)
            if c.parent:
                embed.add_field(name=f'**╚╡**{signature}', value=description)
            else:
                embed.add_field(name=f'{signature} {aliases}', value=description, inline=False)
        embed.set_footer(text=f'Use "{self.clean_prefix}help <command>" for more info on a command.',
                         icon_url=ctx.bot.user.avatar_url)
        await ctx.send(embed=embed)

    async def send_command_help(self, command):
        ctx = self.context

        if await command.can_run(ctx):
            embed = discord.Embed(title=f'Help with `{command.name}`',
                                  color=ctx.bot.config_cache[ctx.guild.id][
                                      'colour'] if ctx.guild else discord.Colour.blurple())
            embed.set_author(
                name=f'We are currently looking at the {command.cog.qualified_name} cog and its command {command.name}',
                icon_url=ctx.author.avatar_url)
            signature = self.get_command_signature(command)
            description = self.get_command_help(command)
            aliases = self.get_command_aliases(command)

            if command.parent:
                embed.add_field(name=f'**╚╡**{signature}', value=description, inline=False)
            else:
                embed.add_field(name=f'{signature} {aliases}', value=description, inline=False)
            embed.set_footer(text=f'Use "{self.clean_prefix}help <command>" for more info on a command.')
            await ctx.send(embed=embed)

    async def send_group_help(self, group):
        ctx = self.context
        bot = ctx.bot

        embed = discord.Embed(title=f'Help with `{group.name}`', description=bot.get_command(group.name).help,
                              color=bot.config_cache[ctx.guild.id]['colour'] if ctx.guild else discord.Colour.blurple())
        embed.set_author(
            name=f'We are currently looking at the {group.cog.qualified_name} cog and its command {group.name}',
            icon_url=ctx.author.avatar_url)
        for command in group.walk_commands():
            if await command.can_run(ctx):
                signature = self.get_command_signature(command)
                description = self.get_command_description(command)
                aliases = self.get_command_aliases(command)

                if command.parent:
                    embed.add_field(name=f'**╚╡**{signature}', value=description, inline=False)
                else:
                    embed.add_field(name=f'{signature} {aliases}', value=description, inline=False)
        embed.set_footer(text=f'Use "{self.clean_prefix}help <command>" for more info on a command.')
        await ctx.send(embed=embed)

    async def send_error_message(self, error):
        pass

    async def command_not_found(self, string):
        ctx = self.context
        command_names = [command.name for command in ctx.bot.commands]
        close_commands = difflib.get_close_matches(string, command_names, len(command_names), 0)
        joined = "\n".join(f'`{command}`' for command in close_commands[:2])

        embed = discord.Embed(
            title='Error!', description=f'**Error 404:** Command or category "{string}" not found ¯\_(ツ)_/¯\n'
                                        f'Perhaps you meant:\n{joined}',
            color=ctx.bot.config_cache[ctx.guild.id]['colour_bad'] if ctx.guild else discord.Colour.red()
        )
        embed.add_field(name='The current loaded cogs are',
                        value=f'(`{"`, `".join([cog for cog in ctx.bot.cogs])}`) :gear:')
        await self.context.send(embed=embed)


class Help(commands.Cog):
    """Need help? Try these with <@630008145162272778> help <command>"""

    def __init__(self, bot):
        self.process = Process()
        self.bot = bot
        self._original_help_command = bot.help_command
        bot.help_command = HelpCommand()
        bot.help_command.cog = self

    def cog_unload(self):
        self.bot.help_command = self._original_help_command

    def get_uptime(self) -> str:
        delta_uptime = datetime.utcnow() - self.bot.launch_time
        hours, remainder = divmod(int(delta_uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)
        return f'`{days}d, {hours}h, {minutes}m, {seconds}s`'

    def format_commit(self, commit) -> str:
        short, _, _ = commit.message.partition('\n')
        short_sha2 = commit.hex[0:6]
        commit_tz = timezone(timedelta(minutes=commit.commit_time_offset))
        commit_time = datetime.fromtimestamp(commit.commit_time).replace(tzinfo=commit_tz)

        # [`hash`](url) message (offset)
        offset = human_timedelta(commit_time.astimezone(timezone.utc).replace(tzinfo=None), accuracy=1)
        return f'[`{short_sha2}`](https://github.com/Gobot1234/Epic-Bot/commit/{commit.hex}) {short} ({offset})'

    def get_last_commits(self, count=3) -> str:
        repo = pygit2.Repository('.git')
        commits = list(islice(repo.walk(repo.head.target, pygit2.GIT_SORT_TOPOLOGICAL), count))
        return '\n'.join(self.format_commit(c) for c in commits)

    @commands.command(aliases=['info'])
    async def stats(self, ctx):
        # memory_usage = self.process.memory_full_info().uss
        rawram = virtual_memory()
        embed = discord.Embed(title=f'**{self.bot.user.name}** - Official Bot Server Invite & Bot information',
                              url='https://discord.gg/h8chCgW',
                              description=f'**Commands loaded & Cogs loaded:** `{len(self.bot.commands)}` commands loaded, '
                                          f'`{len(self.bot.cogs)}` cogs loaded :gear:\n\n'
                                          f'**Latest Changes:**\n{self.get_last_commits()}\n',
                              colour=self.bot.config_cache[ctx.guild.id][
                                  'colour'] if ctx.guild else discord.Colour.blurple(),
                              timestamp=datetime.now())
        embed.set_author(name=str(self.bot.owner), icon_url=self.bot.owner.avatar_url)
        embed.set_thumbnail(url=self.bot.user.avatar_url)

        # statistics
        total_bots = 0
        total_members = 0
        total_online = 0
        total_idle = 0
        total_dnd = 0
        total_offline = 0

        online = discord.Status.online
        idle = discord.Status.idle
        dnd = discord.Status.dnd
        offline = discord.Status.offline

        for member in self.bot.get_all_members():
            if member.bot:
                total_bots += 1
            elif member.status is online:
                total_online += 1
                total_members += 1
            elif member.status is idle:
                total_idle += 1
                total_members += 1
            elif member.status is dnd:
                total_dnd += 1
                total_members += 1
            elif member.status is offline:
                total_offline += 1
                total_members += 1
        total_unique = len(self.bot.users)

        text = 0
        voice = 0
        guilds = 0
        for guild in self.bot.guilds:
            guilds += 1
            for channel in guild.channels:
                if isinstance(channel, discord.TextChannel):
                    text += 1
                elif isinstance(channel, discord.VoiceChannel):
                    voice += 1
        embed.add_field(name='Members', value=f'`{total_members}` <:discord:626486432793493540> total\n'
                                              f'`{total_unique}`:star: unique'
                                              f'\n`{total_bots}` :robot: bots')
        embed.add_field(name='Statuses', value=f'`{total_online}` <:OnlineStatus:659012420735467540> online, '
                                               f'`{total_idle}` <:IdleStatus:659012420672421888> idle,\n'
                                               f'`{total_dnd}` <:DNDStatus:659012419296952350> dnd, '
                                               f'`{total_offline}` <:OfflineStatus:659012420273963008> offline.')
        embed.add_field(name='Servers & Channels',
                        value=f'{guilds} total servers\n{text + voice} total channels\n{text} text chanels\n{voice} voice channels')
        # pc info
        embed.add_field(name="<:compram:622622385182474254> RAM Usage",
                        value=f'Using `{naturalsize(rawram[3])}` / `{naturalsize(rawram[0])}` `{round(rawram[3] / rawram[0] * 100, 2)}`% ')
        # f'of your physical memory and `{naturalsize(memory_usage)}` of which unique to this process.')
        embed.add_field(name='<:cpu:622621524418887680> CPU Usage',
                        value=f'`{cpu_percent()}`% used'
                              f'\n\n:arrow_up: Uptime\n {self.bot.user.mention} has been online for: {self.get_uptime()}')
        embed.add_field(name=':exclamation:Command prefix',
                        value=f'Your command prefix is `{ctx.prefix}`. Type {ctx.prefix}help to list the '
                              f'commands you can use')
        embed.add_field(name='Version info:',
                        value=f'<:dpy:622794044547792926>: `{discord.__version__}`, '
                              f'<:python:622621989474926622>: `{python_version()}`', inline=False)
        embed.set_footer(text="If you need any help join the help server of this code discord.gg",
                         icon_url=ctx.author.avatar_url)
        await ctx.send(embed=embed)

    @commands.command()
    async def avatar(self, ctx, member: discord.Member = None):
        """Get a member's avatar with links to download/view in higher quality"""
        member = member or ctx.author
        embed = discord.Embed(
            title=f'{member.display_name}\'s avatar',
            description=f'[PNG]({member.avatar_url_as(format="png")}) | '
                        f'[JPEG]({member.avatar_url_as(format="jpg")}) | '
                        f'[WEBP]({member.avatar_url_as(format="webp")})',
            colour=discord.Colour.blurple()
        )
        if member.is_avatar_animated():
            embed.description += f' | [GIF]({member.avatar_url_as(format="gif")})'
        embed.set_author(name=member.display_name, icon_url=member.avatar_url)
        embed.set_image(url=member.avatar_url_as(format='gif' if member.is_avatar_animated() else 'webp'))
        await ctx.send(embed=embed)

    @commands.command()
    async def user(self, ctx, user: discord.Member):
        shared_guilds = [g for g in self.bot.guilds if g.get_member(ctx.author.id)]
        perms = ' | '.join([perm for perm, val in dict(ctx.author.permissions_in(ctx.channel)).items() if val]).replace("_", " ")

    @commands.command(name='server-info', aliases=['serverinfo'])
    async def server(self, ctx, *, guild_id: int = None):
        """Get info in the current server"""
        if guild_id is not None and await self.bot.is_owner(ctx.author):
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                return await ctx.send(f'Invalid Guild ID given.')
        else:
            guild = ctx.guild

        roles = [role.mention for role in guild.roles if role is not guild.default_role]

        class Secret:
            pass

        secret_member = Secret()
        secret_member.id = 0
        secret_member.roles = [guild.default_role]

        # figure out what channels are 'secret'
        secret = Counter()
        totals = Counter()
        for channel in guild.channels:
            perms = channel.permissions_for(secret_member)
            channel_type = type(channel)
            totals[channel_type] += 1
            if not perms.read_messages:
                secret[channel_type] += 1
            elif isinstance(channel, discord.VoiceChannel) and (not perms.connect or not perms.speak):
                secret[channel_type] += 1

        member_by_status = Counter(str(m.status) for m in guild.members)

        e = discord.Embed()
        e.title = guild.name
        e.add_field(name='ID', value=guild.id)
        e.add_field(name='Owner', value=guild.owner)
        if guild.icon:
            e.set_thumbnail(url=guild.icon_url)

        channel_info = []
        key_to_emoji = {
            discord.TextChannel: '<:text_channel:586339098172850187>',
            discord.VoiceChannel: '<:voice_channel:586339098524909604>',
        }
        for key, total in totals.items():
            secrets = secret[key]
            try:
                emoji = key_to_emoji[key]
            except KeyError:
                continue

            if secrets:
                channel_info.append(f'{emoji} {total} ({secrets} locked)')
            else:
                channel_info.append(f'{emoji} {total}')

        info = []
        features = set(guild.features)
        all_features = {
            'PARTNERED': 'Partnered',
            'VERIFIED': 'Verified',
            'DISCOVERABLE': 'Server Discovery',
            'PUBLIC': 'Server Discovery/Public',
            'INVITE_SPLASH': 'Invite Splash',
            'VIP_REGIONS': 'VIP Voice Servers',
            'VANITY_URL': 'Vanity Invite',
            'MORE_EMOJI': 'More Emoji',
            'COMMERCE': 'Commerce',
            'LURKABLE': 'Lurkable',
            'NEWS': 'News Channels',
            'ANIMATED_ICON': 'Animated Icon',
            'BANNER': 'Banner'
        }

        for feature, label in all_features.items():
            if feature in features:
                info.append(f'{ctx.tick(True)}: {label}')

        if info:
            e.add_field(name='Features', value='\n'.join(info))

        e.add_field(name='Channels', value='\n'.join(channel_info))

        if guild.premium_tier != 0:
            boosts = f'Level {guild.premium_tier}\n{guild.premium_subscription_count} boosts'
            last_boost = max(guild.members, key=lambda m: m.premium_since or guild.created_at)
            if last_boost.premium_since is not None:
                boosts = f'{boosts}\nLast Boost: {last_boost} ({human_timedelta(last_boost.premium_since, accuracy=2)})'
            e.add_field(name='Boosts', value=boosts, inline=False)

        fmt = f'<:OnlineStatus:659012420735467540> {member_by_status["online"]} ' \
              f'<:IdleStatus:659012420672421888> {member_by_status["idle"]} ' \
              f'<:DNDStatus:659012419296952350> {member_by_status["dnd"]} ' \
              f'<:OfflineStatus:659012420273963008> {member_by_status["offline"]}\n' \
              f'Total: {guild.member_count}'

        e.add_field(name='Members', value=fmt, inline=False)
        e.add_field(name='Roles', value=', '.join(roles) if len(roles) < 10 else f'{len(roles)} roles')
        e.set_footer(text='Created').timestamp = guild.created_at
        await ctx.send(embed=e)


def setup(bot):
    bot.add_cog(Help(bot))
