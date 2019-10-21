# SolarEdge network daemon

# Implements a dhcp and a dns server.

import socket
import threading
import struct
import logging
import se.logutils

logger = logging.getLogger(__name__)

# network constants
dhcpDnsBufferSize = 4096
dhcpLeaseTime = 24 * 60 * 60  # 1 day
validMacs = [
    b"\xb8\x27\xeb",  # Raspberry Pi (testing)
    b"\x00\x27\x02",  # SolarEdge
]
dnsTtl = 24 * 60 * 60  # 1 day

dnsPort = 53
dhcpServerPort = 67
dhcpClientPort = 68
dhcpThreadName = "dhcpThread"
dnsThreadName = "dnsThread"

# dhcp message class
class DhcpMsg(object):

    cookie = b"\x63\x82\x53\x63"

    hdrLen = 12
    chaddrLen = 16
    snameLen = 64
    filenameLen = 128
    cookieLen = 4
    addrLen = 4
    dhcpMsgLen = 300

    opCodeRequest = 1
    opCodeReply = 2

    msgTypeDiscover = 1
    msgTypeOffer = 2
    msgTypeRequest = 3
    msgTypeAck = 5

    optCodeSubnetMask = 1
    optCodeRouter = 3
    optCodeDNS = 6
    optCodeHostName = 12
    optCodeRequestedIpAddr = 50
    optCodeLeaseTime = 51
    optCodeMsgType = 53
    optCodeServerId = 54
    optCodeParamReqList = 55
    optCodeEnd = 255

    def __init__(self,
                 op=0,
                 htype=0x01,
                 hlen=6,
                 hops=0,
                 xid=0,
                 secs=0,
                 flags=0x8000,
                 ciaddr=b"\x00\x00\x00\x00",
                 yiaddr=b"\x00\x00\x00\x00",
                 siaddr=b"\x00\x00\x00\x00",
                 giaddr=b"\x00\x00\x00\x00",
                 chaddr=b"\x00" * chaddrLen,
                 sname=b"\x00" * snameLen,
                 filename=b"\x00" * filenameLen,
                 cookie=cookie,
                 options=None):
        self.op = op
        self.htype = htype
        self.hlen = hlen
        self.hops = hops
        self.xid = xid
        self.secs = secs
        self.flags = flags
        self.ciaddr = ciaddr
        self.yiaddr = yiaddr
        self.siaddr = siaddr
        self.giaddr = giaddr
        self.chaddr = chaddr
        self.sname = sname
        self.filename = filename
        self.cookie = cookie
        if options: self.options = options
        else: self.options = []

    def format(self):
        msg = bytearray(struct.pack(">BBBBLHH", self.op, self.htype, self.hlen,
                          self.hops, self.xid, self.secs, self.flags))
        msg += self.ciaddr + self.yiaddr + self.siaddr + self.giaddr
        msg += self.chaddr + b"\x00" * (self.chaddrLen - len(self.chaddr)
                                       )  # pad to fixed length
        msg += self.sname + b"\x00" * (self.snameLen - len(self.sname)
                                      )  # pad to fixed length
        msg += self.filename + b"\x00" * (self.filenameLen - len(self.filename)
                                         )  # pad to fixed length
        msg += self.cookie
        for opt in self.options:
            msg += bytearray(struct.pack(">BB", opt[0], len(opt[1]))) + opt[1]
        msg += chr(self.optCodeEnd)
        msg += b"\x00" * (self.dhcpMsgLen - len(msg))  # pad to minimum message length
        return msg

    def parse(self, msg):
        (self.op, self.htype, self.hlen, self.hops, self.xid, self.secs, self.flags) = \
            struct.unpack(">BBBBLHH", msg[0:self.hdrLen])
        msgPtr = self.hdrLen
        self.ciaddr = msg[msgPtr:msgPtr + self.addrLen]
        msgPtr += self.addrLen
        self.yiaddr = msg[msgPtr:msgPtr + self.addrLen]
        msgPtr += self.addrLen
        self.siaddr = msg[msgPtr:msgPtr + self.addrLen]
        msgPtr += self.addrLen
        self.giaddr = msg[msgPtr:msgPtr + self.addrLen]
        msgPtr += self.addrLen
        self.chaddr = msg[msgPtr:msgPtr + self.hlen]
        msgPtr += self.chaddrLen
        self.sname = msg[msgPtr:msgPtr + self.snameLen]
        msgPtr += self.snameLen
        self.filename = msg[msgPtr:msgPtr + self.filenameLen]
        msgPtr += self.filenameLen
        self.cookie = msg[msgPtr:msgPtr + self.cookieLen]
        msgPtr += self.cookieLen
        self.options = []
        while msgPtr < len(msg):
            optCode = ord(msg[msgPtr])
            if optCode != self.optCodeEnd:
                optLen = ord(msg[msgPtr + 1])
                self.options.append((optCode, msg[msgPtr + 2:msgPtr + 2 + optLen]))
                msgPtr += 2 + optLen
            else:
                msgPtr = len(msg)

    def log(self):
        logger.data("op: %d" % self.op)
        logger.data("htype: %x" % self.htype)
        logger.data("hlen: %d" % self.hlen)
        logger.data("hops: %d" % self.hops)
        logger.data("xid: 0x%08x" % self.xid)
        logger.data("secs: %d" % self.secs)
        logger.data("flags: 0x%04x" % self.flags)
        logger.data("ciaddr: %s", socket.inet_ntoa(self.ciaddr))
        logger.data("yiaddr: %s", socket.inet_ntoa(self.yiaddr))
        logger.data("siaddr: %s", socket.inet_ntoa(self.siaddr))
        logger.data("giaddr: %s", socket.inet_ntoa(self.giaddr))
        logger.data("chaddr: %s", ':'.join(s.encode('hex') for s in self.chaddr[0:self.hlen]))
        logger.data("sname: %s", ''.join(x.encode('hex') for x in self.sname[0:self.sname.find(b"\x00")]))
        logger.data("filename: %s", ''.join(x.encode('hex')for x in self.filename[0:self.filename.find(b"\x00")]))
        logger.data("cookie: %s","0x" + ''.join(x.encode('hex') for x in self.cookie))
        for opt in self.options:
            logger.data("option: %d %s", opt[0],"0x" + ''.join(x.encode('hex') for x in opt[1]))

# dns message class
class DnsMsg(object):

    hdrLen = 12
    queryLen = 4

    def __init__(self,
                 ident=0,
                 flags=0x0000,
                 questions=None,
                 answers=None,
                 auths=None,
                 adds=None):
        self.ident = ident
        self.flags = flags
        if questions: self.questions = questions
        else: self.questions = []
        if answers: self.answers = answers
        else: self.answers = []
        if auths: self.auths = auths
        else: self.auths = []
        if adds: self.adds = adds
        else: self.adds = []

    def parse(self, msg):
        (self.ident, self.flags, nQuestions, nAnswers, nAuths, nAdds) = \
            struct.unpack(">HHHHHH", msg[0:self.hdrLen])
        msgPtr = self.hdrLen
        for i in range(nQuestions):
            qname = self.parseName(msg[msgPtr:])
            msgPtr += len(qname) + 1
            (qtype, qclass) = struct.unpack(">HH",
                                            msg[msgPtr:msgPtr + self.queryLen])
            msgPtr += self.queryLen
            self.questions.append((qname[:-1], qtype, qclass))

    def parseName(self, msg):
        name = ""
        msgPtr = 0
        partLen = ord(msg[msgPtr])
        while partLen > 0:
            name += msg[msgPtr + 1:msgPtr + partLen + 1] + "."
            msgPtr += partLen + 1
            partLen = ord(msg[msgPtr])
        return name

    def format(self):
        msg = bytearray(struct.pack(">HHHHHH", self.ident, self.flags,
                          len(self.questions), len(self.answers),
                          len(self.auths), len(self.adds)))
        for question in self.questions:
            msg += self.formatName(question[0]) + bytearray(struct.pack(
                ">HH", question[1], question[2]))
        for answer in self.answers:
            msg += self.formatName(answer[0]) + bytearray(struct.pack(">HHLH",
                    answer[1], answer[2], answer[3], len(answer[4]))) + answer[4]
        return msg

    def formatName(self, name):
        parts = name.split(".")
        msg = ""
        for part in parts:
            msg += chr(len(part)) + part
        return msg + b"\x00"

    def log(self):
        logger.data("id: %x" % self.ident)
        logger.data("flags: %04x" % self.flags)
        for question in self.questions:
            logger.data("question")
            logger.data("    name: " + question[0])
            logger.data("    type: %04x" % question[1])
            logger.data("    class: %04x" % question[2])
        for answer in self.answers:
            logger.data("answer")
            logger.data("    name: " + answer[0])
            logger.data("    type: %04x" % answer[1])
            logger.data("    class: %04x" % answer[2])
            logger.data("    TTL: %d" % answer[3])
            logger.data("    resource: " + socket.inet_ntoa(answer[4]))

# start thread to handle dhcp requests
def startDhcp(ipAddr, subnetMask, broadcastAddr):
    # handle dhcp requests
    def dhcp():
        logger.debug("starting " + dhcpThreadName)
        ipAddrNum = socket.inet_aton(ipAddr)
        clientIpAddrNum = ipAddrNum[0:3] + chr(ord(ipAddrNum[3]) + 1)
        subnetMaskNum = socket.inet_aton(subnetMask)
        # create the socket
        dhcpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        dhcpSocket.bind(("", dhcpServerPort))
        dhcpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        seq = 0
        while True:
            logger.debug("waiting for DHCP message")
            (msg, addr) = dhcpSocket.recvfrom(dhcpDnsBufferSize)
            seq += 1
            logger.message("-->", seq, msg, addr[0] + ":" + str(addr[1]))
            dhcpRequest = DhcpMsg()
            dhcpRequest.parse(msg)
            if dhcpRequest.chaddr[0:3] in validMacs:  # only consider requests from specific MAC ranges
                dhcpRequest.log()
                if dhcpRequest.options[0][0] == DhcpMsg.optCodeMsgType:
                    if ord(dhcpRequest.options[0][1]) == DhcpMsg.msgTypeDiscover:
                        # respond to discover message with offer
                        dhcpReply = DhcpMsg(
                            op=DhcpMsg.opCodeReply,
                            hlen=dhcpRequest.hlen,
                            xid=dhcpRequest.xid,
                            secs=dhcpRequest.secs,
                            ciaddr=dhcpRequest.ciaddr,
                            yiaddr=clientIpAddrNum,
                            chaddr=dhcpRequest.chaddr,
                            options=[
                                (DhcpMsg.optCodeMsgType, chr(DhcpMsg.msgTypeOffer)),
                                (DhcpMsg.optCodeServerId, ipAddrNum),
                                (DhcpMsg.optCodeLeaseTime, bytearray(struct.pack(">L", (dhcpLeaseTime)))),
                                (DhcpMsg.optCodeSubnetMask, subnetMaskNum),
                                (DhcpMsg.optCodeRouter, ipAddrNum),
                                (DhcpMsg.optCodeDNS, ipAddrNum),
                            ])
                    elif ord(dhcpRequest.options[0][1]) == DhcpMsg.msgTypeRequest:
                        # respond to request message with ack
                        dhcpReply = DhcpMsg(
                            op=DhcpMsg.opCodeReply,
                            hlen=dhcpRequest.hlen,
                            xid=dhcpRequest.xid,
                            secs=dhcpRequest.secs,
                            ciaddr=dhcpRequest.ciaddr,
                            yiaddr=clientIpAddrNum,
                            chaddr=dhcpRequest.chaddr,
                            options=[
                                (DhcpMsg.optCodeMsgType, chr(DhcpMsg.msgTypeAck)),
                                (DhcpMsg.optCodeServerId, ipAddrNum),
                                (DhcpMsg.optCodeLeaseTime, bytearray(struct.pack(">L", (dhcpLeaseTime)))),
                                (DhcpMsg.optCodeSubnetMask, subnetMaskNum),
                                (DhcpMsg.optCodeRouter, ipAddrNum),
                                (DhcpMsg.optCodeDNS, ipAddrNum),
                            ])
                    else:  # ignore other messages
                        dhcpReply = None
                    if dhcpReply:
                        seq += 1
                        dhcpReplyMsg = dhcpReply.format()
                        logger.message("<--", seq, dhcpReplyMsg,
                               broadcastAddr + ":" + str(dhcpClientPort))
                        dhcpReply.log()
                        dhcpSocket.sendto(dhcpReplyMsg, (broadcastAddr, dhcpClientPort))
                        del dhcpReply
                else:
                    logger.info("first option is not message type")
            else:
                logger.debug("ignoring DHCP request from "+
                    ':'.join(x.encode('hex') for x in dhcpRequest.chaddr))
            del dhcpRequest

    dhcpThread = threading.Thread(name=dhcpThreadName, target=dhcp)
    dhcpThread.daemon = True
    dhcpThread.start()

# start thread to handle dns requests
def startDns(ipAddr):
    # handle dns requests
    def dns():
        logger.debug("starting " + dnsThreadName)
        dnsSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        dnsSocket.bind(("", dnsPort))
        seq = 0
        while True:
            logger.debug("waiting for DNS message")
            (msg, addr) = dnsSocket.recvfrom(dhcpDnsBufferSize)
            seq += 1
            logger.message("-->", seq, msg, addr[0] + ":" + str(addr[1]))
            dnsRequest = DnsMsg()
            dnsRequest.parse(msg)
            dnsRequest.log()
            if dnsRequest.questions[0][0] != "NONE":
                seq += 1
                # any hostname will resolve to this IP address
                dnsReply = DnsMsg(
                    ident=dnsRequest.ident,
                    flags=0x8000,
                    questions=dnsRequest.questions,
                    answers=[question + (dnsTtl, socket.inet_aton(ipAddr))
                        for question in dnsRequest.questions])
                dnsReplyMsg = dnsReply.format()
                logger.message("<--", seq, dnsReplyMsg, addr[0] + ":" + str(addr[1]))
                dnsReply.log()
                dnsSocket.sendto(dnsReplyMsg, (addr[0], addr[1]))
                del dnsReply
            else:
                logger.debug("ignoring DNS request with no hostname")
            del dnsRequest

    dnsThread = threading.Thread(name=dnsThreadName, target=dns)
    dnsThread.daemon = True
    dnsThread.start()
