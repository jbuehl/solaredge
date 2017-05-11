"""
The seDataDevices module defines the ParseDevice class, and a number of subclasses thereof.

ParseDevice and it's subclasses are intended to be a reasonably straightforward way of adding new (seType) devices to the
list that the semonitor suite can recognise and can parse.

ParseDevice is a subclass of a dictionary, with a tailored __init__ method. Given a block of seData from a pcap file,
the __init__ method will parse it, and populate the ParseDevice instance with entries mapping items to their parsed
value, as found in the data block.

The top level ParseDevice only performs a rudimentary parse of the data, and returns almost all of it as a hex string.

Subclasses of ParseDevice (eg ParseDevice_0x0030) contain more extensive item definitions (stored in the _defn list) and
populate the dictionary in a more sensible and useful way.  Each subclass is tuned to a specific seType.  _dev defines
the seType the the subclass is designed to parse, and _defn lists the definitions for blocks of data of that seType.

Thanks to some fancy footwork in the __new__ method of ParseDevice itself, it is only ever necessary to try to create an
instance of ParseDevice (ie to code `ParseDevice(data)`).  ParseDevice.__new__ determines the seType of the block of data, by
examining the standard header block in the data.  Then it searches through all the subclasses of ParseDevice that have
been defined, and if one 'tuned' to the seType of the block of data being parsed is found, creates an instance of that
specialised subclass.

There is one extra special subclass of ParseDevice, namely ParseDevice_Explorer.  It is *not* intended for production use.
It operates without any item definitions at all.  Instead it works it's way through the block of seData, in 2 bytes
increments, parsing the next 4 bytes in almost every way they could be parsed.  Almost all of the parsed data items will
be nonsense, but perusing the parsed device - for example by using se2csv and then opening the csv file - may help with
the deciphering of new seType devices. It is an alternative, of sorts, to examining the relevant part of the pcap file
using a hex editor.
"""

import struct
import time
import binascii
try:
    import syslog
except ImportError:
    # Allow for the fact that syslog is not (to my knowledge) available on Windows
    import seWindowsSyslog as syslog

# log a message (used by merge_update)
def log(*args):
    message = args[0]+" "
    for arg in args[1:]:
        message += arg.__str__()+" "
        # todo : Make this align better with the options available elsewhere in semonitor, while retaining the ability
        # todo cont : to import merge_update into modules that need it, like se2csv
    syslog.syslog(message)



# Spacer field for documenting field definitions more neatly, used for convenience
sp = "\n\t\t\t\t\t\t: "
# Create a "utility" constant, to use later to make code less verbose
nan = float('nan')


class ParseDevice(dict) :
    """
    ParseDevice itself can only perform a very basic parse of a block of seData from a pcap file.  It's main purposes
    are :

        to provide a suite of standard methods shared by all the subclasses (and in particular the parseDevTable method
        which given a _defn list, will parse the seData block accordingly); and
        to have a 'clever' __new__ method, which redirects the creation of a ParseDevice to the creation of a subclass of
        a ParseDevice which specialises in the particular seType encountered in the current block of seData (provided of
        course that a specialised subclass for that seType has been defined).
    """

    _dev = 0xffff # dummy value, I hope.  Should be overwritten in subclasses.
    _devName = 'Unknown_device'
    _devType = '{}_{:#06x}'.format(_devName, _dev)

    # DEFINITIONS for items in new devices, filled in for subclasses of ParseDevice.
    #
    # The definition has to be a list not a mapping because field order matters!
    # Each field definition is (also) a list, with 6 members, namely
    # [paramLen, paramInFmt, paramName, outFormatFn (can be None), out (to csv) True or False, comment]

    _defn = [
        # The following standard device header fields are automatically parsed for all device types.
        # These items do *not* need to be defined!
        # [2, 'H', 'seType', lambda hex: '{:#06x}'.format(hex), False, "Identifies the type of this solar edge data block],
        # [4, 'L', 'seId', parseId, False, "Identifies the solar edge device"],
        # [2, 'H', 'devLen', None, False, "Length in bytes of the data block"],
    ]

    # DERIVATIONS, optional, can be left empty if not required.
    #
    # List of names of derived items.
    # Useful for documenting the interpretation of the derived values, and is also
    # used to set the default values (in case the condition which
    # triggers the derivation does not occur at a particular timeStamp) - see the setDerivationDefaults method.

    # Each "definition" is itself a list, comprising:
    # [paramName, paramDefault, out (to csv) True or False, comment]
    #
    # NB *** It is (much) simpler to describe the actual derivation for a particular item in Python code
    # (within the subclass that needs it) than to develop a completely new "syntax" for describing derivations!
    # see the codeDerivations method in the subclasses of ParseDevice for examples.

    _derivn = [
        # [paramName, paramDefault, out (to csv) True or False, comment]
    ]

    # HYPOTHESES, optional, list of (valid Python) expressions which I expect to be always true.
    # Useful for generating debug alerts in the event of "new" unexpected values appearing in data items.
    # See ParseDevice_0x0030 for an example.
    _hypotheses = []

    def __new__(cls, data, explorer=False):
        # Some fancy footwork so that I can always start to create a ParseDevice, but actually get a subclass which is
        # appropriate for the seType encountered in the data block (provided a subclass specific to the seType has been
        # defined, of course).
        devHdrLen = 8
        (seType, seId, devLen) = struct.unpack("<HLH", data[0:devHdrLen])

        # Search for a subclass which can handle this seType
        for subclass in cls.__subclasses__():
            if subclass._dev == seType:
                return(subclass(data))

        # Otherwise either return a ParseDevice_Explorer (explorer=True),
        # which is a special subclass which will parse almost anything,
        # albeit with quite a number of nonsense parsings interspersed with occasional correctly parsed fields,
        # or just return a bare minimum instance of a dictionary (explorer=False).
        if explorer:
            # return a special ParseDevice which tries almost every field parsing it knows about
            return ParseDevice_Explorer(data)
        else:
            # return an instance of a basic dictionary (the base class for ParseDevice itself)
            newInstance = super(ParseDevice, cls).__new__(cls)
            # (Re)setting a basically empty (unknown) definition for this instance is crucial
            # because you may have already encountered another unknown device with a *different* length and _defn,
            # and the parseDevTable method updates the *class* definition dynamically if it encounters more data than it
            # expects!.
            newInstance._defn = [
                [4, 'L', "dateTime", "dateTime", False, "Seconds since the epoch"]
            ]
            return newInstance

    @staticmethod
    def parseId(seId):
        return ("%x" % (seId & 0xff7fffff)).upper()

    # format a date
    @staticmethod
    def formatDateStamp(timeStamp):
        return time.strftime("%Y-%m-%d", time.localtime(timeStamp))

    # format a time
    @staticmethod
    def formatTimeStamp(timeStamp):
        return time.strftime("%H:%M:%S", time.localtime(timeStamp))

    # format a hex entry as a readable string
    @staticmethod
    def hexData(data):
        """
        Convert a string of bytes into a nicely formatted string of the hex representation of each byte.

        :param data: A string of bytes.
        :return: A longer string, containing a hex representation of the data bytes, formatted for easiser reading.
        """
        lineSize = 16
        def hexLine(data):
            return ' '.join(x.encode('hex') for x in data)

        hexLines = []
        if data != "":
            printPtr = 0
            while len(data) - printPtr >= lineSize:
                hexLines.append(hexLine(data[printPtr:printPtr + lineSize]))
                printPtr += lineSize
            if printPtr < len(data):
                hexLines.append(hexLine(data[printPtr:]))
        return ' | '.join(hexLines)

    @staticmethod
    def unhexData(hexData):
        """
        Convert a hex representation into a string of bytes, ie the inverse of hexData.

        :param hexData: String, containing a (must be valid) hex representation of some bytes.
        :return: The string of bytes corresponding to hexData.
        """
        return binascii.unhexlify(hexData.replace("|","").replace(" ",""))

    def __init__(self, data, explorer=False):
        self.parseDevTable(data)
        self.setDerivationDefaults()
        self.codeDerivations()
        self.checkHypotheses()

    def parseDevTable(self, data):

        dataPtr = 0
        devHdrLen = 8
        # device header
        (seType, seId, devLen) = struct.unpack("<HLH", data[dataPtr:dataPtr + devHdrLen])
        dataPtr += devHdrLen

        # For (almost) all subclasses, _devType will already have this value.
        # This is necessary only when a default catchall parse is happening, because a specific parser for seType has
        # not been defined.
        self._devType = '{}_{:#06x}'.format(self._devName, seType)
        # Store seId as an attribute for later use as part of the standard "dictionary of dictionaries" wrapper when
        # a parsed instance is converted to json.
        self._seId = self.parseId(seId)

        self.update({'seType': '{:#06x}'.format(seType),
                     'seId': self._seId,
                     'devLen': devLen,
                     'devType' : self._devType}
                    )

        if self.defnLen > devLen :
            raise ValueError('You have defined more bytes, {}, than the message contains, {}'.format(self.defnLen, devLen))
        elif self.defnLen < devLen :
            # By default, convert any remaining undefined bytes to their representation as a hexadecimal string.
            self._defn.append([devLen - self.defnLen, 'hex', "Undeciphered_data", self.hexData, True, "Unknown as yet" ])

        for paramLen, paramInFmt, paramName, outFormatFn, out, comment in self._defn:
            # Extract the field
            if paramInFmt == 'hex':
                self[paramName] = data[dataPtr: dataPtr + paramLen]
            # Check for a specific value which I believe should be interpreted as nan
            # In little endian format '\xff\xff\x7f\xff' unpacks -3.402...*10**38.
            # But the solaredge messages seem to use it to signify "not reported".
            # In all the cases I have encountered it makes more sense to interpret this particular float value as NaN
            # rather than as a very large negative number, so that is what I do below.
            # Note that if unpacked in **big** endian format, this special value actually unpacks as nan.
            # I suspect a legacy "bug" somewhere in the solaredge messages, but in the meantime just check the bytes
            # and fix it.
            elif paramInFmt == 'f' and (data[dataPtr: dataPtr + paramLen] == '\xff\xff\x7f\xff'):
                self[paramName] = float('nan')
            else:
                self[paramName] = struct.unpack('<' + paramInFmt, data[dataPtr: dataPtr + paramLen])[0]


            # Optionally format the field
            if outFormatFn == 'dateTime':
                try:
                    self['Date'] = self.formatDateStamp(self[paramName])
                except ValueError:
                    # se2graphite will not like this 'error' value for a Date field, but it should be OK in se2csv
                    self['Date'] = "{} is not a valid date".format(self[paramName])
                try:
                    self['Time'] = self.formatTimeStamp(self[paramName])
                except ValueError:
                    self['Time'] = "{} is not a valid time".format(self[paramName])
            elif outFormatFn is not None:
                self[paramName] = outFormatFn(self[paramName])
            dataPtr += paramLen
        return

    def setDerivationDefaults(self):
        for paramName, paramDefault, out, comment in self._derivn:
            self[paramName] = eval(paramDefault)

    def codeDerivations(self):
        # Subclasses should override this if they want to calculate any derivations.
        pass

    def checkHypotheses(self):
        for hypothesis in self._hypotheses:
            if not eval(hypothesis):
                msg = ["Failed hypothesis",  self.__class__.__name__, self["Date"], self["Time"], ":",
                       hypothesis, "is not True"]
                logging.warn(" ".join(msg))

    def wrap_in_ids(self):
        """
        "Wrap" the dictionary of parsed data items inside a "dictionary of dictionary" structure (like invDict etc)
        based on the device type and device id(s), to uniquely identify each device instance.  The standard
        identifiers are devType and seId, but some device types (eg batteries and optimisers) may have alternative
        and/or additional identifiers following the devType (in which case the subclass parsers for those devices
        should override this method with their own identifiers).

        The full name structure of the metric is embedded in the "dict of dict" structure, and so the data items
        (aka metrics) from this device can be distinguished from any data items reported by other devices.

        :return: The (parsed) device attributes, "wrapped" in dictionary of dictionaries based on device type and device
          identifiers.
        """
        return {self._devType: {self._seId : self}}


    @classmethod
    def itemNames(cls):
    # Extract some item name and definition length information that se2csv needs

        # devItemNames = ["seType", "seId", "devLen", "devType"] These are "uninteresting" and will not be output to csv
        # Extract a list of the names of "interesting" items, that will routinely be sent to csv and graphite.
        devItemNames = [name for itemLen, fmt, name, outFmt, out, comment in cls._defn if out]
        devItemNames.extend([paramName for paramName, paramDefault, out, comment in cls._derivn if out])
        # 1 Find the dateTime output format entry (if it exists) and insert additional separate Date and Time items
        try:
            iDateTime = [outFmt for itemLen, fmt, name, outFmt, out, comment in cls._defn].index('dateTime')# + 3
            devItemNames.insert(iDateTime, "Time")
            devItemNames.insert(iDateTime, "Date")
        except ValueError:
            pass  # The dateTime field has not been identified/defined yet
        return devItemNames

    @property
    def defnLen(self):
        return sum([itemLen for itemLen, fmt, name, outFmt, out, comment in self._defn])

    @classmethod
    def itemDefs(cls):
        """
        Produce a pretty report on the item definitions parsed by this class, and it's subclasses.

        :return: A formatted string, (usually) extracted from _defn and _derivn.
        """
        msg = ["\n\n{} / {} parses data blocks with seType = {:#06x}.\n{}".format(cls.__name__, cls._devType, cls._dev, "="*80)]
        msg.append("Items are:")
        itemLine = "{:<4} ({:^6})   {:<6} | {:<25} \n\t\t\t\t\t\t: {:<0}\n"
        msg.append(itemLine.format("Byte", "Length", "Word", "Item Name",  "Meaning"))
        msg.append(itemLine.format("_"*4, "_"*6, "_"*6, "_"*25, "_"*40))
        byte = 0
        word = byte / 4.0
        if len(cls._defn) > 0:
            for paramLen, paramInFmt, paramName, outFormatFn, out, comment in cls._defn:
                msg.append(itemLine.format(byte, paramLen, word, paramName, comment))
                byte += paramLen
                word = byte / 4.0
        if len(cls._derivn) > 0:
            msg.append("Derived items\n")
            for paramName, paramDefault, out, comment in cls._derivn:
                msg.append(itemLine.format('----', '------', '----', paramName, '(default={}) {}'.format(paramDefault,comment)))
        for subclass in cls.__subclasses__():
            msg.append(subclass.itemDefs())
        return "\n".join(msg)


class ParseDevice_0x0030(ParseDevice) :

    def __new__(cls, data):
        # Create a bare minimum instance of a dictionary.  ALL subclasses of ParseDevice MUST do this.
        # NB This step is essential, because otherwise, when this subclass was instantiated / created, it would call
        # the __new__ method of ParseDevice itself, which would redirect the creation to this subclass, and so on until
        # the recursion limit was reached!
        # PS Note that a more usual idiom would be super(ParseDevice_0x0030, cls).__new__(cls), but this is what we
        # are trying to avoid!
        return super(ParseDevice, cls).__new__(cls)

    _dev =0x0030
    _devName = 'batteries'
    _devType = '{}_{:#06x}'.format(_devName, _dev)
    _defn = [
        # device specific fields
        #  [paramLen, paramInFmt, paramName, outFormatFn (can be None), out (to csv or graphite) True or False, comment]
        [4, 'L', "dateTime", "dateTime", False, "Seconds since the epoch"],
        [12, '12s', "batteryId", None, True, "Identifier for this battery"],
        [4, 'f', 'Vdc', None, True, "Volts"],
        [4, 'f', 'Idc', None, True, "Amps"],
        [4, 'f', 'BattCapacityNom', None, True,"Wh, Nameplate Energy Capacity"],
        [4, 'f', 'BattCapacityActual', None, True, "Wh, Actual Battery Capacity now"],
        [4, 'f', 'BattCharge', None, True, "Wh, Energy Stored now"],
        [4, 'L', 'TotalEnergyIn', None, True, 'Wh, Lifetime Energy Input to Battery'],
        [4, 'f', 'AlwaysZero_40_float', None, False, "Unused"],
        [4, 'L', 'TotalEnergyOut', None, True, "Wh, Lifetime Energy Output by Battery"],
        [4, 'f', 'AlwaysZero_48_float', None, False, "Unused"],
        [4, 'hex', 'HexConst_52', ParseDevice.hexData, False, "Unknown, constant value"],
        [4, 'hex', 'HexConst_56', ParseDevice.hexData, False, "Unknown, constant value"],
        [4, 'f', 'Temp', None, True, "degrees C, Battery Temperature"],
        [2, 'H', 'BattChargingStatus', None, True, "3=>Charging, 4=>Discharging, 6=>Holding"],
        [4, 'f', 'AlwaysZero_66_float', None, False, "Unused"],
        [4, 'f', 'AlwaysZero_70_float', None, False, "Unused"],
        [4, 'L', 'Interval', None, False, "Seconds, Time Interval"],
        [4, 'L', 'EIn', None, True, "Wh, Energy into battery during interval"],
        [4, 'L', 'EOut', None, True, "Wh, Energy out of battery during interval"],
    ]

    _hypotheses = [
        "abs(self['AlwaysZero_40_float']) < 10**25",
        "abs(self['AlwaysZero_48_float']) < 10**25",
        "abs(self['AlwaysZero_66_float']) < 10**25",
        "abs(self['AlwaysZero_70_float']) < 10**25",
    ]

    def wrap_in_ids(self):
        """
        "Wrap" the dictionary of parsed data items inside a "dictionary of dictionary" structure (like invDict etc)
        based on the device type and device id(s), to uniquely identify each device instance.  The standard
        identifiers are devType and seId, but some device types (eg batteries and optimisers) may have alternative
        and/or additional identifiers following the devType (in which case the subclass parsers for those devices
        should override this method with their own identifiers).

        The full name structure of the metric is embedded in this "dict of dict" structure, and so the data items
        (aka metrics) from this device can be distinguished from any data items reported by other devices.

        :return: The (parsed) device attributes, "wrapped" in dictionary of dictionaries base on device type and device
          identifiers.
        """
        return {self._devType: {self._seId: {self["batteryId"]: self}}}


class ParseDevice_0x0022(ParseDevice) :

    def __new__(cls, data):
        # Create a bare minimum instance of a dictionary.
        # NB This step is essential, because otherwise, when this subclass was instantiated / created, it would call
        # the __new__ method of ParseDevice itself, which would redirect the creation to this subclass, and so on until
        # the recursion limit was reached!
        return super(ParseDevice, cls).__new__(cls)

    _dev =  0x0022
    _devName = 'meters'
    _devType = '{}_{:#06x}'.format(_devName, _dev)
    _defn = [
        # device specific fields
        #  [paramLen, paramInFmt, paramName, outFormatFn (can be None), out (to csv or graphite) True or False, comment]
        [4, 'L', "dateTime", "dateTime", False, "Seconds since epoch"],
        [1, 'b', "recType", None, True, "record Type, determines the interpretation of later fields" +
             sp + "3=Consumption," +
             sp + "5=Grid Import/Export," +
             sp + "7=Battery," +
             sp + "8=Unknown, almost all 0,or very very small," +
             sp + "9=PV production"],
        [1, 'b', "onlyIntervalData", None, True, "1=only interval data has been reported, 0=lifetime data reported as well"],

        [4, 'L', 'TotalE2Grid', None, True, "Wh, Lifetime energy exported to grid (*provided* onlyIntervalData flag is not set)" +
             sp + "Wh. Total lifetime energy exported to grid when recType=5 (matches SE LCD panel value)" +
             sp + "always 0, when recType=3, or 7, or 8, or 9 because onlyIntervalData=1 (True)" ],
        [2, 'H', 'AlwaysZero_off10_int2', None, False, "Padding"],
        [2, 'hex', 'Flag_off12_hex', ParseDevice.hexData, True, "Flag" +
             sp + "0x0000->TotalE2Grid reported" +
             sp + "0x0080->TotalE2Grid not reported"],
        [4, 'L', 'TotalEfromGrid', None, True, "Wh, Lifetime energy imported from grid (*provided* onlyIntervalData flag is not set)" +
             sp + "Wh. Total lifetime energy imported from grid when recType=5 (matches SE LCD panel value)" +
             sp + "always 0, when recType=3, or 7, or 8, or 9 because onlyIntervalData=1 (True)"],
        [2, 'H', 'AlwaysZero_off18_int2', None, False, "Padding"],
        [2, 'hex', 'Flag_off20_hex', ParseDevice.hexData, True, "Flag" +
             sp + "0x0000->TotalEfromGrid reported" +
             sp + "0x0080->TotalEfromGrid not reported"],
        [4, 'L', 'Totaloff22_int4', None, True, "Unknown, probably an energy field  (*provided* lifetime flag is set)" +
             sp + "Maybe a cumulative net value, it appears to decrease overnight when importing power" +
             sp + "Wh. Unknown when recType=5 (generally increasing trend, but falls overnight)" +
             sp + "always 0, when recType=3, or 7, or 8, or 9 because onlyIntervalData=1 (True)"],
        [2, 'H', 'AlwaysZero_off26_int2', None, False, "Padding"],
        [2, 'hex', 'Flag_off28_hex', ParseDevice.hexData, True, "Flag" +
             sp + "0x0000->Totaloff22_int4 reported" +
             sp + "0x0080->Totaloff22_int4 not reported"],
        [4, 'L', 'Totaloff30_int4', None, True, "Unknown total energy field (*provided* lifetime flag is set)" +
             sp + "monotonic increasing so far including overnight." +
             sp + "Maybe something like cum total consumption scaled by about 60%?" +
             sp + "Wh. Unknown when recType=5 (steadily increasing trend)" +
             sp + "always 0, when recType=3, or 7, or 8, or 9 because onlyIntervalData=1 (True)"],
        [2, 'H', 'AlwaysZero_off34_int2', None, False, "Padding"],
        [2, 'hex', 'Flag_off36_hex', ParseDevice.hexData, True, "Flag" +
             sp + "0x0000->Totaloff30_int4 reported" +
             sp + "0x0080->Totaloff30_int4 not reported"],
        [4, 'L', 'Interval', None, True, "Seconds, Time Interval"],
        [4, 'L', 'E2X', None, True, "Wh, Energy to X during the interval" +
             sp + "always 0 when recType=3" +
             sp + "Wh. Energy exported to grid during interval when recType=5 (whenever TotalE2Grid is static, E2X=0)" +
             sp + "Wh. Energy into battery when recType=7 (matches battery(0x0030).EIn)" +
             sp + "Unknown, when recType=8 (almost always 0, very occasionally has small +ive value)" +
             sp + "Wh. PV energy production during interval when recType=9"
         ],
        [4, 'L', 'EfromX', None, True, "Wh, Energy in from X during interval " +
             sp + "Wh. Consumption when recType=3" +
             sp + "Wh. Energy imported from grid during interval when recType=5 (whenever TotalEfromGrid is static, EfromX=0)" +
             sp + "always 0 when recType=7 (I expected E from battery but it does not match battery(0x0030).EOut)" +
             sp + "always 0 when recType=8 " +
             sp + "always 0 when recType=9"
         ],
        [4, 'f', 'P2X', None, True, "W, Power output to X" +
             sp + "always nan when recType=3" +
             sp + "W. Power to grid at end of interval when recType=5 (whenever TotalE2Grid is static, P2X=0)" +
             sp + "W. Power into battery when recType=7 (is nonzero when E2X is nonzero)" +
             sp + "almost always 0 when recType=8 " +
             sp + "W. PV power when recType=9"
         ],
        [4, 'f', 'PfromX', None, True, "W, Power input from X" +
             sp + "W. Consumption when recType=3" +
             sp + "W. Power from grid at end of interval when recType=5 (whenever TotalEfromGrid is static, PfromX=0)" +
             sp + "always nan when recType=7" +
             sp + "always nan when recType=8" +
             sp + "always nan when recType=9"
         ],
    ]

    _derivn = [
        # [paramName, paramDefault, out (to csv) True or False, comment]
    ]

    _hypotheses = [
        "self['AlwaysZero_off10_int2'] == 0",
        "self['AlwaysZero_off18_int2'] == 0",
        "self['AlwaysZero_off26_int2'] == 0",
        "self['AlwaysZero_off34_int2'] == 0",
    ]

    def __init__(self, data, explorer=False):
        super(ParseDevice_0x0022, self).__init__(data)

    def codeDerivations(self):
        # Filter out some sporadic 'nan'-like values which appear in P2X.  The hex value is the BIG endian version
        # of a Python nan.  Read as LITTLE endian it becomes "-3.2... 10^38" which is unlikely to be meant as a real value!
        # Most of these are filtered out later, but occasionally if the interval is short one slips through anyway.
        # Short intervals appear to happen about once a day, perhaps when the inverter is going to sleep for the night.
        if self['P2X'] < -3*10**38:
            self["P2X"] = nan


    def wrap_in_ids(self):
        """
        "Wrap" the dictionary of parsed data items inside a "dictionary of dictionary" structure (like invDict etc)
        based on the device type and device id(s), to uniquely identify each device instance.  The standard
        identifiers are devType and seId, but some device types (eg batteries and optimisers) may have alternative
        and/or additional identifiers following the devType (in which case the subclass parsers for those devices
        should override this method with their own identifiers).

        The full name structure of the metric is embedded in this "dict of dict" structure, and so the data items
        (aka metrics) from this device can be distinguished from any data items reported by other devices.

        Because there are multiple reported 0x0022 entries in a typical pcap file, all with the same timestamp, it is
        *essential* to distinguish them by means of the recType, otherwise almost all the reported metrics end up being
        overwritten by the next 0x0022 entry!

        :return: The (parsed) device attributes, "wrapped" in dictionary of dictionaries base on device type and device
          identifiers.
        """
        recTypeLabels = {
            3 : "3_Consumption",
            5 : "5_GridImportExport",
            7 : "7_Battery",
            8 : "8_MostlyZeroes",
            9 : "9_PVProduction"
        }
        recTypeLabel = recTypeLabels.get(self["recType"], "{}_UnrecognisedRecType".format(self["recType"]))
        return {self._devType: {self._seId: {recTypeLabel :self}}}


class ParseDevice_Explorer(ParseDevice) :
    """ A special parser which tries out several different ways of interpreting each item in the data message, and
    reports *ALL* of them.

    Most of the parsed values will be wrong, but hopefully by inspection you can find the parsings which make sense.

    Intended for exploring new devices type by either looking at the raw json file, or by using se2csv and looking at
    the csv file.  Once the correct interpretations for each item have been determined, a new subclass of
    ParseDevice tailored to those items should be constructed."""

    def __new__(cls, data):
        # Create a bare minimum instance of a dictionary.
        # NB This step is essential, because otherwise, when this subclass was instantiated / created, it would call
        # the __new__ method of ParseDevice itself, which would redirect the creation to this subclass, and so on until
        # the recursion limit was reached!
        return super(ParseDevice, cls).__new__(cls)

    _dev = 0xffff # dummy value since ParseDevice_Explorer will "parse" any seType (albeit overly enthusiastically!)
    _devName = 'explore'
    _devType = '{}_{:#06x}'.format(_devName, _dev)
    _defn = []
    _itemNames = ["seType", "seId", "devLen", "devType"]
    _defnLen = 0

    def parseDevTable(self, data):
        """ A special exploratory parser, that works without a pre-defined list of itemNames and definitions. Somewhere
        amongst the plethora of parsed values it produces, there will be the correct interpretation of each item.
        I hope!

        It does presume all devices begin with a standard "seType, seID, devLen" header, which may not be correct.

        :param data: The data to be parsed, in as many ways as possible.
        :return: A dictionary of item names and (possible) parsed data items.
        """
        dataPtr = 0
        devHdrLen = 8
        # device header
        (seType, seId, devLen) = struct.unpack("<HLH", data[dataPtr:dataPtr + devHdrLen])

        self._dev = seType
        self._defnLen = devLen
        # For standard subclasses, _devType will already have this value.
        # However ParseDevice_Explorer can be used as a default parser, when a new device is encountered, in which case
        # the actual instance value of seType would be unknown when the seDataDevices module was imported (or in other
        # words, ParseDevice_Explorer._dev will contain a nonsense value which must be corrected when real data is read)
        self._devType = '{}_{:#06x}'.format(self._devName, seType)
        self._seId = seId


        dataPtr += devHdrLen
        self.update({'seType': '{:#06x}'.format(seType),
                     'seId': self.parseId(seId),
                     'devLen': devLen,
                     'devType' : self._devType}
                    )

        # First, dump a hex version of the whole block into one field
        self["AllAsHex"] = self.hexData(data[dataPtr:])
        # Next work through the block, 2 bytes at a time, tryinag as many potential parsings as will fit.
        # I am assuming items will be at least 2 bytes long.  Easy enough to change if you need to try different offsets.
        for offset in range(0, devLen, 2):
            # Parse a range of possible interpretations of the (4) bytes beginning at offset.
            self.parseAtOffset(data[dataPtr:], offset, devLen)
        return


    def parseAtOffset(self, data, offset, devlen):
        """
        Parses (up to) 4 bytes of data, beginning at offset, as many ways as it can.

        :param data: The complete data message.
        :param offset: The beginning point for the 4 bytes to be parsed.
        :param devlen: The length of the data message (we cannot parse beyond this!)
        :return: None, but entries are added into self (the dictionary of itemName -> parsedValue)
        """

        if offset <= (devlen - 1):
            # Parse items which may be 1 byte long
            itemName = "offset{:03}_1_hex1".format(offset)
            self[itemName] = self.hexData(data[offset: offset + 1])
            self._itemNames.append(itemName)

        if offset <= (devlen - 2):
            # Parse items which may be 2 bytes long
            itemName = "offset{:03}_1_hex2".format(offset)
            self[itemName] = self.hexData(data[offset: offset + 2])
            self._itemNames.append(itemName)
            itemName = "offset{:03}_4_int2".format(offset)
            self[itemName] = struct.unpack("<H", data[offset: offset + 2])[0]
            self._itemNames.append(itemName)

        if offset <= (devlen - 4):
            # Parse items which may be 4 bytes long
            itemName = "offset{:03}_1_hex4".format(offset)
            self[itemName] = self.hexData(data[offset: offset + 4])
            self._itemNames.append(itemName)
            itemName = "offset{:03}_3_float_LE".format(offset)
            self[itemName] = struct.unpack("<f", data[offset: offset + 4])[0]
            self._itemNames.append(itemName)
            itemName = "offset{:03}_3_float_BE".format(offset)
            self[itemName] = struct.unpack(">f", data[offset: offset + 4])[0]
            self._itemNames.append(itemName)
            itemName = "offset{:03}_4_int4".format(offset)
            self[itemName] = struct.unpack("<L", data[offset: offset + 4])[0]
            self._itemNames.append(itemName)
            # Maybe it is a date?
            try:
                self["Date_offset{:03}".format(offset)] = self.formatDateStamp(self[itemName])
                self["Time_offset{:03}".format(offset)] = self.formatTimeStamp(self[itemName])
                # Other modules (eg se2graphite) become upset if Date and Time are not supplied, so take the 1st valid
                # Date we find. Implicitly I'm guessing that offset zero will be the "real" date.
                if "Date" not in self.keys():
                    self["Date"] = self.formatDateStamp(self[itemName])
                    self["Time"] = self.formatTimeStamp(self[itemName])
            except ValueError:
                # Apparently it is not a date!
                self["Date_offset{:03}".format(offset)] = '{} is not a Date'.format(self[itemName])
                self["Time_offset{:03}".format(offset)] = '{} is not a Time'.format(self[itemName])
            self._itemNames.append("Date_offset{:03}".format(offset))
            self._itemNames.append("Time_offset{:03}".format(offset))

    @classmethod
    def itemNames(cls):
        # Warning.  If ParseDevice_Explorer is used on more than 1 seType data block in a single run, this will *NOT*
        # return sensible values!
        return cls._itemNames

    @property
    def defnLen(self):
        return self._defnLen

    @classmethod
    def itemDefs(cls):
        msg = ["\n\n{} / {} parses data blocks with any unrecognised seType.\n{}".format(cls.__name__, cls._devType, "="*80)]
        msg.append("Each pair/quadruple of bytes is parsed multiple times, using a number of different fields types.")
        msg.append("Item names are generated automatically, signalling the offset where the bytes began")
        msg.append("and the Python field type they have been parsed as.")
        msg.append("Inspecting the parsed fields (eg using se2csv) and identifying sensible and/or recognised values is")
        msg.append("a step towards deciphering a new seType block, and creating a more sensible parser for it.")
        return '\n'.join(msg)


def unwrap_metricsDict(mydict):
    """
    A iterator/generator function to "flatten" (aka unwrap) the attributes stored in the parsed device dictionaries,
    after they have been wrapped in the device type and device id identifiers.  The inverse (sort of) to the
    ParseDevice.wrap_in_ids method.

    Will work equally well on a json.loads dictionary (where the json was created from a parsed device dictionary).

    :param mydict: A nested set of dictionaries, the deepest level of which records the attributes for a device.  "Date"
     must be one of those device attributes, because that is how the algorithm knows it has reached the bottom of the
     nest.

    :return: A graphite style structured name for the device instance, and a {name: value} dictionary of it's attributes.
    """
    def nice(k):
        # Remove characters which give graphite or open (a file) problems.
        # Also remove an extra level of naming (devices) that I don't really need anymore.
        # Todo tidy up and delete the removal of "devices" when testing is over.
        return str(k).replace("\x00", '').replace(" ", "_").replace("devices", "")
    for k, v in mydict.iteritems():
        if "Date" in v.keys():
            yield nice(k), v
        else:
            for k2, v2 in unwrap_metricsDict(v):
                if len(nice(k2)) == 0:
                    # Silently drop this extra level of naming
                    yield nice(k), v2
                elif len(nice(k)) == 0:
                    # Silently drop this extra level of naming
                    yield nice(k2), v2
                else:
                    yield "{}.{}".format(nice(k), nice(k2)), v2

def merge_update(dict1, dict2):
    """
    A recursive function which updates a master nested dictionary (dict1) with **only the new** elements of a
    smaller contributor nested dictionary (dict2).

    :param dict1: The master nested dictionary.
    :param dict2: A new subsidiary nested dictionary, to be merged into dict1.
    :return: None, but the master dictionary is updated with **only** the new parts of dict2 merged in.
    """
    for k2, v2 in dict2.iteritems():
        if k2 not in dict1.keys():
            dict1.update({k2: v2})
        elif isinstance(v2, dict):
            merge_update(dict1[k2], v2)
        elif dict1[k2] == v2:
            # We have a duplicated value being reported by se.  I presume it is an updated value.
            pass
        else:
            # We have reached the bottom of the dictionary of dictionaries structure and still have no NEW identifier keys
            # So it looks like the inverter has reported new attributes for an existing instance identifier in the same message
            message = "WARNING : For {} about to overwrite {} with {}".format(k2, dict1[k2], v2)
            log(message)
            dict1[k2] = v2
