"""
Script: DiscordReport
Author: [UBGE] DiaZ
Description: A simple script who allow a player to send a Report message in-game Directly to one or more Discord Channel/Server
-----------
Remember to Modify the ROLE_MENTION & WEBHOOK_URL TO THIS SCRIPT WORK PROPERLY
Command: /report <#ID/Nickname> <Message>
Comando: /reportar <#ID/Nickname> <Mensagem>
"""

from asyncio.log import logger
import urllib
import urllib2
import thread
from commands import add, name, get_player, join_arguments, alias
from pyspades.constants import *
from pyspades.server import *

USER_AGENT = "Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:47.0) Gecko/20100101 Firefox/47.0"
WEBHOOK_URL = "WEBHOOK_URL_HERE"
LANGUAGE = "EN" #PT/EN
ROLE_MENTION = "<@!ID_NUMBER_HERE>" #Discord role Mention ID (Optional) FORMAT: <@!ID_NUMBER_HERE>
REPORT_MESSAGE_PT = "**%s** esta reportando o player: **%s**.\n**Motivo**: %s.\n**Servidor**: %s.\nIP: %s\n%s"
REPORT_MESSAGE_EN = "**%s** is reporting player: **%s**.\n**Reason**: %s.\n**Server**: %s.\nIP: %s\n%s"

@name('report')
@alias("reportar")
def report(connection, value, *arg):
    #Declaration of Pysnip Constants and Variables
    player = get_player(connection.protocol, value)
    message = join_arguments(arg)
    player_name = player.name
    protocol = connection.protocol
    
    if LANGUAGE is "PT":
        notMessageReturn = "Digite o comando no seguinte formato: /reportar <#ID/Nickname> <Mensagem>"
        reportMsg = REPORT_MESSAGE_PT % (connection.name, player_name, message, protocol.name, protocol.identifier, ROLE_MENTION)
        exceptionMessage = "Uma excecao ocorreu!"
        reportReturnMessage = 'O report foi enviado com Sucesso para a Equipe STAFF'

    if LANGUAGE is "EN":
        notMessageReturn = "Type the command in the following Format: Command: /report <#ID/Nickname> <Message>"
        reportMsg = REPORT_MESSAGE_EN % (connection.name, player_name, message, protocol.name, protocol.identifier, ROLE_MENTION)
        exceptionMessage = "A exception has occurred!"
        reportReturnMessage = "The report has successfully sended to Staff Team"
    
    if not message:
        return notMessageReturn

    try:
        url=WEBHOOK_URL
        data = urllib.urlencode({"content": reportMsg})
        post_request = urllib2.Request(url, data)
        post_request.add_header("User-Agent", USER_AGENT)
        urllib2.urlopen(post_request).read()
    except:
        return exceptionMessage
    return reportReturnMessage

add(report)

def apply_script(protocol, connection, config):


    class SendReportClass(connection):
    
# WILL BE IMPLEMENTED IN A FUTURE RELEASE
        def send_report(connection, message, url):
            url=WEBHOOK_URL
            data = urllib.urlencode({"content": message})
            post_request = urllib2.Request(url, data)
            post_request.add_header("User-Agent", USER_AGENT)
            thread.start_new_thread(urllib2.urlopen(post_request).read())
            return connection.enviar_report
    return protocol, SendReportClass
