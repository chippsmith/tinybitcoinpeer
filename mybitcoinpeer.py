import gevent.monkey; gevent.monkey.patch_all()   # needed for PySocks!
import gevent
import gevent.socket as socket
from gevent.queue import Queue
import bitcoin
from bitcoin.messages import *
from bitcoin.net import CAddress, CInv
from bitcoin.core import b2lx, b2x, CTransaction, CTxIn

import time
import contextlib
import io
import random

###forked tiny bitcoinpper to send 'getdata' message in response to 'inv' message to get all the transactions
### Also added sending "getaddr" message and parsed addr message in return and wrote results to ips.txt


COLOR_RECV = '\033[95m'
COLOR_SEND = '\033[94m'
COLOR_ENDC = '\033[0m'



# Select bitcoin p2p params using python-bitcoinlib
bitcoin.SelectParams('mainnet')
PORT = bitcoin.params.DEFAULT_PORT


# Get DNS seeds, exclude schildbach, which is offline, and add provoost.
SEEDS = [x[1] for x in bitcoin.params.DNS_SEEDS if "schildbach" not in x[1]]
SEEDS.append("seed.testnet.bitcoin.sprovoost.nl")

LOCATOR = bitcoin.net.CBlockLocator()
LOCATOR.vHave.append(bitcoin.params.GENESIS_BLOCK.GetHash())

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
                print(f"recieved", {len(msg.headers)}, "headers")
                ##print("headers: ", msg.headers)
                LOCATOR.vHave.append(msg.headers[-1].GetHash())
                send(f, msg_getblocks(LOCATOR))
            ### write a file called ips.txt to collect all the addresses sent by our peers
            elif msg.command == b'addr':
                print(msg.addrs)
                for a in msg.addrs:
                    print(a.ip)
                    file = open('ips.txt', "a")
                    file.write(f" \'{a.ip}\', \n")

                continue
            ### if message is inventory message respond with getdata message to recieve the transactions or blocks
            elif msg.command == b'inv':
                transaction_list = msg.inv
                for transactions in msg.inv:
                    transaction_hash = b2lx(transactions.hash)
                    ##print("transaction hash recieved: ", transaction_hash)
                send(f, get_data_pkt(transaction_list))

            elif msg.command == b"tx":
                ##TODO parse tx message
                pass

            elif msg.command == b"block":
                ###TODO parse block message
                pass
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
    msg.strSubVer = b"/mybitcoinpeer.py/"
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

def get_data_pkt(transaction_list):
    msg = msg_getdata()
    invs = transaction_list
    msg.inv = invs
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