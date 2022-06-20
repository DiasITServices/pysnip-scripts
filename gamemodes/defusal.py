"""
Creator: 10se1ucgo
------------------
A lot of this code is pretty confusing
Why? Because I suck at this kind of programming! Woo!
Hey, at least it runs. Maybe I'll port it to Iceball.
I completely regret my decision in making this.
Note: There might be some broken stuff. Haven't been able to test this that much.
"""
from __future__ import division
import random
import time

from twisted.internet.error import AlreadyCalled, AlreadyCancelled
from twisted.internet.reactor import callLater
from twisted.internet.task import LoopingCall

from commands import add, name
from pyspades.collision import distance_3d
from pyspades.common import Vertex3
from pyspades.constants import *
from pyspades.server import chat_message, grenade_packet
from pyspades.world import Grenade

HIDE_POS = (0, 0, 63)
EXPLOSION_MULTIPLIER = 1.2
ROUND_TIME = 120  # In seconds

# These are default values that can be overwritten by map extensions. (In seconds)
BOMB_TIME = 40
BOMB_RADIUS = 40
PLANT_TIME = 5
DEFUSE_TIME = 5

S_PICKUP_C4 = "You picked up the C4 explosive, take it to the bombsite!"
S_ACTION_CHAT = "I'm {action} the bomb."
S_ACTION_MSG = "{action} bomb: {time} seconds remaining. Sneak (Default: V) or change weapons to cancel."
S_CANT_ACTION = "You must have your BLOCK TOOL out in order to {action} the bomb!"

S_BOMB_PLANTED = "Bomb has been planted. {time} seconds until detonation."
S_BOMB_DEFUSED = "{player} defused the bomb with {time} seconds remaining"
S_CT_WIN_DEFUSED = "Bomb has been defused. Counter-Terrorists win."
S_CT_WIN = "Conter-Terrorists win"
S_T_WIN = "Terrorists win."
S_DRAW = "Time ran out! No team wins."

S_NOT_ENOUGH_PLY = "Both teams require at least one player to start."
S_ROUND_START = "Begin round!"
S_ROUND_LIMIT = "Time limit for this round: {time} seconds."
S_TIME_LEFT = "Time left in round: {time} seconds."
S_NO_ROUND_RUNNING = "Round hasn't started!"


@name("timeleft")
def get_time_remaining(connection):
    if connection.protocol.de_running:
        remaining = connection.protocol.de_limit_call.getTime() - time.time()
        return S_TIME_LEFT.format(time=round(remaining))
    return S_NO_ROUND_RUNNING
add(get_time_remaining)


# From arena.py
def get_team_dead(team):
    for player in team.get_players():
        if not player.world_object.dead:
            return False
    return True


def send_chat_as_player(connection, value, global_message):
    chat_message.player_id = connection.player_id
    chat_message.value = value
    chat_message.chat_type = [CHAT_TEAM, CHAT_ALL][int(global_message)]
    connection.protocol.send_contained(chat_message, team=None if global_message else connection.team)


def calculate_bomb_force(bomb_pos, player_pos, blast_radius):
    distance = distance_3d(bomb_pos, player_pos)
    if distance > blast_radius:
        return 0
    return EXPLOSION_MULTIPLIER - distance / blast_radius


def apply_script(protocol, connection, config):
    if config.get('game_mode', 'ctf') != 'ctf':
        return protocol, connection

    class DefusalProtocol(protocol):

        def on_map_change(self, new_map):
            opts = self.map_info.extensions
            if not opts or not opts.get('defusal'):
                self.de_enabled = False
                self.de_running = False
                return protocol.on_map_change(self, new_map)

            self.building = False
            self.green_team.de_spawn = opts.get('de_green_spawn', HIDE_POS)
            self.blue_team.de_spawn = opts.get('de_blue_spawn', HIDE_POS)

            self.de_bomb_site = opts.get('de_bomb_site', (HIDE_POS, HIDE_POS))
            self.de_bomb_time = opts.get('de_bomb_time', BOMB_TIME)
            self.de_bomb_radius = opts.get('de_bomb_radius', BOMB_RADIUS)
            self.de_defuse_time = opts.get('de_defuse_time', DEFUSE_TIME)
            self.de_plant_time = opts.get('de_plant_time', PLANT_TIME)

            self.de_new_round(first=True)

            return protocol.on_map_change(self, new_map)

        def on_base_spawn(self, x, y, z, base, entity_id):
            if not self.de_enabled:
                return protocol.on_base_spawn(self, x, y, z, base, entity_id)

            if entity_id == GREEN_BASE:
                return self.de_spawn_bombsite()

            return HIDE_POS

        def on_flag_spawn(self, x, y, z, flag, entity_id):
            if not self.de_enabled:
                return protocol.on_flag_spawn(self, x, y, z, flag, entity_id)

            if entity_id == BLUE_FLAG:
                return self.green_team.de_spawn

            return HIDE_POS

        def de_delay_plant(self, connection):
            # If I don't round it is_integer() doesn't work properly. (for some reason)
            self._de_current_defuser = connection
            remaining = round(self.de_plant_time - self.de_plant_timer, 1)
            self.de_plant_timer += 0.08
            connection.set_location(self.de_plant_pos)
            if remaining.is_integer():
                connection.send_chat(S_ACTION_MSG.format(action="Planting", time=remaining))

            if connection and connection.world_object.sneak or connection.tool != BLOCK_TOOL:
                self.de_stop_plant(canceled=True, connection=connection)
                callLater(2, self.de_reset_cooldowns)  # Resets cooldown (sets plant_timer to 0). Python lambdas SUCK :(
                return

            if self.de_plant_timer < self.de_plant_time:
                return

            self.de_stop_plant(canceled=False, connection=connection)
            self.de_plant_bomb(connection)

        def de_stop_plant(self, canceled, connection):
            connection.de_planting = False
            self.de_plant_loop.stop()
            self.blue_team.flag.player.drop_flag() if self.blue_team.flag.player else None
            self.de_plant_pos = (0, 0, 0) if canceled else self.de_plant_pos  # We use this later for the explosion.
            self.de_plant_timer = 1 if canceled else 0  # Setting to 1 makes the int eval as True (for cooldown)

        def de_plant_bomb(self, connection):
            if self.de_bomb_call and self.de_bomb_call.active():
                return
            if self.de_limit_call and self.de_limit_call.active():
                self.de_limit_call.cancel()
            self.de_planter = connection
            self.de_bomb_call = callLater(self.de_bomb_time, self.de_bomb_explode)
            self.send_chat(S_BOMB_PLANTED.format(time=self.de_bomb_time))

            player_pos = connection.get_location()

            self.green_team.flag.set(player_pos[0], player_pos[1], self.map.get_z(player_pos[0], player_pos[1]))
            self.green_team.flag.update()

            self.green_team.base.set(*HIDE_POS)
            self.green_team.base.update()

            self.blue_team.flag.set(*HIDE_POS)
            self.blue_team.flag.update()

        def de_bomb_explode(self):
            if self.de_defuse_loop:
                self.de_stop_defuse(canceled=True)
            # Borrowed from (mostly) airstrike.py
            for _ in range(12):
                x, y, z = self.de_spawn_bombsite()
                position = Vertex3(x, y, z)
                velocity = Vertex3(0.0, 0.0, 0.0)
                grenade_object = self.world.create_object(Grenade, 0.0, position, None, velocity,
                                                          self.de_planter.grenade_exploded)
                grenade_object.name = "c4"
                grenade_packet.value = grenade_object.fuse
                grenade_packet.player_id = self.de_planter.player_id
                grenade_packet.position = position.get()
                grenade_packet.velocity = velocity.get()
                self.send_contained(grenade_packet)

            self.de_running = False
            self.send_chat(S_T_WIN)
            for player in self.players.values():  # values() gives us a set (removes duplicates from MultikeyDict.)
                # linear model because im lazy as fak
                damage = calculate_bomb_force(self.de_plant_pos, player.get_location(), self.de_bomb_radius) * 100
                if damage:
                    player.hit(value=damage, by=self.de_planter, type=GRENADE_KILL)
            callLater(2, self.de_new_round, winner=self.green_team)

        def de_delay_defuse(self, connection):
            remaining = round(self.de_defuse_time - self.de_defuse_timer, 1)
            self.de_defuse_timer += 0.08
            connection.set_location(self.de_defuse_pos)
            if remaining.is_integer():
                connection.send_chat(S_ACTION_MSG.format(action="Defusing", time=remaining))

            if connection and connection.world_object.sneak or connection.tool != BLOCK_TOOL:
                self.de_stop_defuse(canceled=True, connection=connection)
                callLater(2, self.de_reset_cooldowns)  # Resets cooldown (sets plant_timer to 0). Python lambdas SUCK :(
                return

            if self.de_defuse_timer < self.de_defuse_time:
                return

            try:
                self.de_bomb_call.cancel()
            except (AlreadyCancelled, AlreadyCalled):
                return
            self.de_defuser = connection
            self.de_stop_defuse(canceled=False, connection=connection)
            self.de_running = False
            bomb_time = self.de_bomb_call.getTime() - time.time()
            self.send_chat(S_CT_WIN_DEFUSED)
            self.send_chat(S_BOMB_DEFUSED.format(player=self.de_defuser.name, time=bomb_time))
            callLater(2, self.de_new_round, winner=self.blue_team)

        def de_stop_defuse(self, canceled, connection=None):
            # Explained in de_stop_plant
            if connection:
                connection.de_defusing = False
            else:
                self._de_current_defuser.de_defusing = False
                self._de_current_defuser = None
            self.de_defuse_loop.stop()
            self.green_team.flag.player.drop_flag() if canceled and self.green_team.flag.player else None
            self.de_defuse_pos = (0, 0, 0) if canceled else self.de_defuse_pos
            self.de_defuse_timer = 1 if canceled else 0

        def de_spawn_bombsite(self):
            x = random.randint(self.de_bomb_site[0][0], self.de_bomb_site[1][0])
            y = random.randint(self.de_bomb_site[0][1], self.de_bomb_site[1][1])
            try:
                z = random.randint(self.de_bomb_site[0][2], self.de_bomb_site[1][2])
            except IndexError:
                z = self.map.get_z(x, y)
            return (x, y, z)

        def de_new_round(self, first=False, winner=False):
            self.de_enabled = True  # Whether or not Defusal should run on this map
            self.de_running = False  # Whether or not the round is running

            if not first:
                if self.de_bomb_call and self.de_bomb_call.active():
                    self.de_bomb_call.cancel()
                if self.de_limit_call and self.de_limit_call.active():
                    self.de_limit_call.cancel()
                # If this isn't the first round, we respawn all of the objects.
                self.green_team.flag.player.drop_flag() if self.green_team.flag.player else None
                self.green_team.flag.set(*HIDE_POS)
                self.green_team.flag.update()
                self.green_team.base.set(*self.de_spawn_bombsite())
                self.green_team.base.update()

                self.blue_team.flag.player.drop_flag() if self.blue_team.flag.player else None
                self.blue_team.flag.set(*self.green_team.de_spawn)
                self.blue_team.flag.update()
                self.blue_team.base.set(*HIDE_POS)
                self.blue_team.base.update()

            for team in (self.blue_team, self.green_team):
                if team.count() == 0:
                    self.send_chat(S_NOT_ENOUGH_PLY)
                    callLater(5, self.de_new_round, first=True)
                    return

            if winner:
                self.de_capture_flag(winner=winner)
            else:
                self.de_running = True
            if winner is None:
                self.send_chat(S_DRAW)

            self.de_respawn()

            self.send_chat(S_ROUND_START)
            self.send_chat(S_ROUND_LIMIT.format(time=ROUND_TIME))

            self.de_limit_call = callLater(ROUND_TIME, self.de_new_round, winner=None)

            self.de_defuser = None  # Connection object of the bomb defuser
            self.de_planter = None  # Connection object of the bomb planter

            self.de_plant_pos = (0, 0, 0)  # Location in which the bomb was planted
            self.de_plant_timer = 0.0  # Time since bomb plant began. (Reset to 0 after plant is over)
            self.de_plant_loop = None  # The twisted LoopingCall object that calls the de_delay_plant function

            self.de_defuse_pos = (0, 0, 0)  # Location in which the bomb was defused
            self.de_defuse_timer = 0.0  # Time since bomb defuse began. (Reset to 0 after defuse is over)
            self.de_defuse_loop = None  # The twisted LoopingCall object that calls the de_delay_defuse function
            self.de_bomb_defused = False

            self.de_bomb_call = None  # The twisted callLater object that explodes the bomb if not cancelled.

        def de_capture_flag(self, winner):
            player = self.de_planter if winner == self.green_team else self.de_defuser
            if not (player and player.team == winner):
                player = random.choice(list(winner.get_players()))
            if player.world_object.dead:
                player.spawn(winner.de_spawn)
            player.take_flag()
            player.capture_flag()
            self.de_running = True

        def de_respawn(self):
            # Taken from arena.py
            for player in self.players.values():  # values() gives us a set (removes duplicates from MultikeyDict.)
                player.de_defusing = False
                player.de_planting = False
                if player.team.spectator:
                    continue

                if player.world_object.dead:
                    player.spawn(player.team.de_spawn)
                else:
                    player.set_location(player.team.de_spawn)
                    player.refill()

        def de_check_end(self):
            if not self.de_running:
                return

            if get_team_dead(self.green_team):
                if self.de_bomb_call:
                    if self.de_bomb_call.active():
                        # Ts still have a chance to win if the CTs are out of time
                        return
                    else:
                        # The only way that I know how to check if a callLater has been cancelled.
                        try:
                            self.de_bomb_call.cancel()
                        except (AlreadyCancelled, AlreadyCalled):
                            # Let the defuse or explosion routine handle the win
                            return
                self.de_running = False
                self.send_chat(S_CT_WIN)
                callLater(2, self.de_new_round, winner=self.blue_team)

            elif get_team_dead(self.blue_team):
                if self.de_bomb_call:
                    try:
                        self.de_bomb_call.cancel()
                    except (AlreadyCalled, AlreadyCancelled):
                        # Let the defuse or explosion routine handle the win
                        return
                self.de_running = False
                self.send_chat(S_T_WIN)
                callLater(2, self.de_new_round, winner=self.green_team)

        def de_reset_cooldowns(self):
            # Why can't lambdas have assignments :(
            # Python needs anonymous functions
            self.de_plant_timer = 0
            self.de_defuse_timer = 0

    class DefusalConnection(connection):
        de_defusing = False
        de_planting = False

        def de_cancel_everything(self):
            if self.de_defusing:
                self.protocol.de_stop_defuse(canceled=True, connection=self)
            if self.de_planting:
                self.protocol.de_stop_plant(canceled=True, connection=self)

        # A lot of these hooks are modified from arena.py

        def on_disconnect(self):
            if self.protocol.de_running:
                self.de_cancel_everything()
                if self.world_object is not None:
                    self.world_object.dead = True
                    self.protocol.de_check_end()
            return connection.on_disconnect(self)

        def on_team_join(self, team):
            ret = connection.on_team_join(self, team)
            if ret is False:
                return ret
            if self.protocol.de_running:
                self.de_cancel_everything()
                if self.world_object is not None and not self.world_object.dead:
                    self.world_object.dead = True
                    self.protocol.de_check_end()
            return ret

        def get_respawn_time(self):
            if self.protocol.de_running:
                return -1
            elif self.protocol.de_enabled:
                return 0
            return connection.get_respawn_time(self)

        def respawn(self):
            if self.protocol.de_running:
                self.de_cancel_everything()
                return False
            return connection.respawn(self)

        def on_spawn(self, position):
            ret = connection.on_spawn(self, position)
            if self.protocol.de_running:
                self.de_cancel_everything()
                self.kill()
            return ret

        def on_spawn_location(self, pos):
            if self.protocol.de_enabled:
                self.de_cancel_everything()
                return self.team.de_spawn
            return connection.on_spawn_location(self, pos)

        def on_kill(self, killer, type, grenade):
            if self.protocol.de_running:
                if self.world_object is not None:
                    self.world_object.dead = True
                    self.protocol.de_check_end()
            if self.protocol.de_running:
                self.de_cancel_everything()

            return connection.on_kill(self, killer, type, grenade)

        def on_refill(self):
            ret = connection.on_refill(self)
            if self.protocol.de_running:
                return False
            return ret

        def on_flag_take(self):
            if not self.protocol.de_enabled or not self.protocol.de_running:
                return connection.on_flag_take(self)

            if self.team == self.protocol.green_team:
                if self.protocol.de_bomb_call and self.protocol.de_bomb_call.active():
                    return False

                self.send_chat(S_PICKUP_C4)
                return connection.on_flag_take(self)

            elif (self.protocol.de_bomb_call and self.protocol.de_bomb_call.active() and
                  self.team == self.protocol.blue_team):
                if self.protocol.de_bomb_defused or self.protocol.de_defuse_timer:
                    return False

                if self.tool != BLOCK_TOOL:
                    self.send_chat(S_CANT_ACTION.format(action="defuse"))
                    return False

                ret = connection.on_flag_take(self)
                self.de_defusing = True
                send_chat_as_player(self, S_ACTION_CHAT.format(action="defusing"), global_message=False)
                self.protocol.de_defuse_pos = self.get_location()
                self.protocol.de_defuse_loop = LoopingCall(self.protocol.de_delay_defuse, self)
                self.protocol.de_defuse_loop.start(0.08)
                return ret

            return False

        def capture_flag(self):
            if not self.protocol.de_enabled or not self.protocol.de_running:
                return connection.capture_flag(self)

            if self.protocol.de_bomb_call and self.protocol.de_bomb_call.active() or self.protocol.de_plant_timer:
                return False

            if self.team == self.protocol.green_team:
                if self.tool != BLOCK_TOOL:
                    self.send_chat(S_CANT_ACTION.format(action="plant"))
                    return False

                send_chat_as_player(self, S_ACTION_CHAT.format(action="planting"), global_message=False)
                self.protocol.de_plant_pos = self.get_location()
                self.protocol.de_plant_loop = LoopingCall(self.protocol.de_delay_plant, self)
                self.protocol.de_plant_loop.start(0.08)

            return False

    return DefusalProtocol, DefusalConnection