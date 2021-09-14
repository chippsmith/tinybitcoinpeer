#!/usr/bin/env python
# tinybitcoinpeer.py
#
# A toy bitcoin node in Python. Connects to a random testnet
# node, shakes hands, reacts to pings, and asks for pongs.
# - Andrew Miller https://soc1024.com/
#
# Thanks to Peter Todd, Jeff Garzik, Ethan Heilman
#
# Dependencies: 
# - gevent
# - https://github.com/petertodd/python-bitcoinlib
# 
# This file is intended to be useful as a starting point 
# for building your own Bitcoin network tools. Rather than
# choosing one way to do things, it illustrates several 
# different ways... feel free to pick and choose.
# 
# - The msg_stream() function handily turns a stream of raw
#     Bitcoin p2p socket data into a stream of parsed messages.
#     Parsing is provided by the python-bitcoinlib dependency.
#
# - The handshake is performed with ordinary sequential code.
#    You can get a lot done without any concurrency, such as
#     connecting immediately to fetching blocks or addrs,
#     or sending payloads of data to a node.

# - The node first attempts to resolve the DNS name of a Bitcoin
#     seeder node. Bitcoin seeder speak the DNS protocol, but
#     actually respond with IP addresses for random nodes in the
#     network.
#
# - After the handshake, a "message handler" is installed as a
#     background thread. This handler logs every message
#     received, and responds to "Ping" challenges. It is easy
#     to add more reactive behaviors too.
#
# - This shows off a versatile way to use gevent threads, in
#     multiple ways at once. After forking off the handler
#     thread, the main thread also keeps around a tee of the
#     stream, making it easy to write sequential schedules.
#     This code periodically sends ping messages, sleeping
#     in between. Additional threads could be given their
#     own tees too.
#

import gevent.monkey; gevent.monkey.patch_all()   # needed for PySocks!
import gevent
import gevent.socket as socket
from gevent.queue import Queue
import bitcoin
from bitcoin.messages import *
from bitcoin.net import CAddress
import time
import contextlib
import io
import random

COLOR_RECV = '\033[95m'
COLOR_SEND = '\033[94m'
COLOR_ENDC = '\033[0m'

# Select bitcoin p2p params using python-bitcoinlib
bitcoin.SelectParams('testnet')
PORT = bitcoin.params.DEFAULT_PORT

# Get DNS seeds, exclude schildbach, which is offline, and add provoost.
SEEDS = [x[1] for x in bitcoin.params.DNS_SEEDS if "schildbach" not in x[1]]
SEEDS.append("seed.testnet.bitcoin.sprovoost.nl")

# Set a global block locator for testnet to the Genesis Block (used for getheaders)
LOCATOR = bitcoin.net.CBlockLocator()
LOCATOR.vHave.append(bitcoin.params.GENESIS_BLOCK.GetHash())


# Turn a raw stream of Bitcoin p2p socket data into a stream of 
# parsed messages.
def msg_stream(f):
    f = io.BufferedReader(f)
    while True:
        yield MsgSerializable.stream_deserialize(f)
        

def send(sock, msg): 
    print(COLOR_SEND, 'Sent:    ', COLOR_ENDC, msg.command)
    msg.stream_serialize(sock)


def tee_and_handle(f, msgs):
    queue = Queue()     # unbounded buffer

    def _run():
        for msg in msgs:
            print(COLOR_RECV, 'Received:', COLOR_ENDC, msg.command)     # print `msg` for full message
            if msg.command == b'ping':
                send(f, msg_pong(nonce=msg.nonce))
            elif msg.command == b'headers':
                # Update global with new best block header hash
                LOCATOR.vHave.append(msg.headers[-1].GetHash())
            queue.put(msg)
    t = gevent.Greenlet(_run)
    t.start()
    while True:
        yield queue.get()


def version_pkt(my_ip, their_ip):
    msg = msg_version()
    # Leave this at 60002 unless you also patch python-bitcoinlib to match
    # If you send messages (e.g. get_headers) with mis-matching versions, remote peer will disconnect
    msg.nVersion = 60002
    msg.addrTo.ip = their_ip
    msg.addrTo.port = PORT
    msg.addrFrom.ip = my_ip
    msg.addrFrom.port = PORT
    msg.strSubVer = b"/tinybitcoinpeer.py/"
    return msg


def addr_pkt(str_addrs):
    msg = msg_addr()
    addrs = []
    for i in str_addrs:
        addr = CAddress()
        addr.port = PORT
        addr.nTime = int(time.time())
        addr.ip = i
        addrs.append(addr)
    msg.addrs = addrs
    return msg


def main():
    with contextlib.closing(socket.socket()) as s, \
         contextlib.closing(s.makefile('wb', 0)) as writer, \
         contextlib.closing(s.makefile('rb', 0)) as reader:

        # This will return a random testnet node from a DNS seed
        their_ip = socket.gethostbyname(random.choice(SEEDS))
        print(" Connecting to:", their_ip)

        my_ip = "127.0.0.1"

        s.connect((their_ip, PORT))
        stream = msg_stream(reader)

        # Send Version packet
        send(writer, version_pkt(my_ip, their_ip))

        # Receive their Version
        their_ver = next(stream)
        print(COLOR_RECV, 'Received:', COLOR_ENDC, their_ver)

        # Send Version acknowledgement (Verack)
        send(writer, msg_verack())

        # Fork off a handler, but keep a tee of the stream
        stream = tee_and_handle(writer, stream)

        # Get Verack
        their_verack = next(stream)
        print(COLOR_RECV, 'Received:', COLOR_ENDC, their_verack)

        t = 0
        try:
            while True:
                send(writer, msg_ping())
                if t == 2:
                    # Get some addresses
                    send(writer, msg_getaddr())
                if t == 4:
                    # Get some headers
                    _h = msg_getheaders()
                    _h.locator = LOCATOR
                    send(writer, _h)
                gevent.sleep(5)
                t += 1
        except KeyboardInterrupt:
            pass


main()
