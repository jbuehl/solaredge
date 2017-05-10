# Understanding ParseDevice

### Audience

This documentation is intended for people who want to understand how
`ParseDevice` works, and possibly are interested in extending it to cope
with a new device type they have encountered in the stream of data sent
from a solaredge system to the solaredge website.  Readers are expected
to have a reasonable working knowledge of Python, be comfortable
with how Python classes and subclasses work, and be willing to read the
code for a definitive understanding of what is happening.  It aims to
explain the motivation and broad structure of the `ParseDevice` class,
rather than to document its API precisely. Or put another way, it is
more like a tutorial or cookbook  than a manual.

---

## A very brief overview of `ParseDevice`.

`ParseDevice` is a subclass of a Python dictionary (`dict`) with a
tailored `__init__` method.  Given a block of your data, captured from
messages sent by a solaredge system, it extracts the `seType` from the
header then uses a list of field definitions to parse the data block,
and initialises itself with entries which map each field name to the
corresponding field value found in the data block.

New devices (i.e new `seType` values) can be defined by creating a
subclass of `ParseDevice` with an appropriate list of field definitions.

The `ParseDict.__new__` method is *smart*, in that it consults the list
of subclasses which is automatically maintained by Python, and delegates
the parsing to an appropriate subclass if one exists.  Effectively you
only ever need to try to create a `ParseDevice` instance; new device
definitions in subclasses are invoked without any further intervention
necessary.

There is provision in `ParseDict` for subclasses to define a list of
derived fields, if required, and to code more complex derivations (for
example ones requiring bit shifting) via a hook method, `codeDerivations`.

Some devices (eg optimisers, batteries, and the 0x0022 `seType`, which I
have called meters) send multiple messages for the same timepoint.
Existing code in seData.py distinguishes such multiple messages by storing
their parsed values in an appropriately named dictionary.  For example,
parsed messages (device attributes) from different optimisers are kept in
a dictionary, `optDict`, indexed by the `seId` which identifies each
optimiser.

`ParseDict` expands and generalises this concept, essentially by
introducing a master dictionary (`devsDict`) of device dictionaries. For
explanatory purposes, you could think of entries in `devsDict` being
made via code in seData.py something like :

```python
    devsDict["inverters"] = invDict
    devsDict["optimisers"] = optDict
    devsDict["events"] = eventDict
```

In practice, this is implemented slightly differently.  The task of
"wrapping" the parsed device attributes for a specific instance of a
device into this *nested dictionaries* type of structure
is delegated to `ParseDict` (or  subclass), by means of a method called
`wrap_in_ids`.  It is most easily understood via the code itself - here
is the default method from `ParseDict` itself :

```python
    def wrap_in_ids(self):
        return {self._devType: {self._seId : self}}
```

Subclasses which require additional identifiers simply define a
deeper set of *nested dictionaries*.  For example (should you be lucky
enough to need to distinguish attributes from more that one battery!),
`ParseDevice_0x0030`, which parses battery messages, defines :

```python
    def wrap_in_ids(self):
        return {self._devType: {self._seId: {self["batteryId"]: self}}}
```

All that seData.py then has to do is merge the "wrapped" dictionary of
dictionaries into its master dictionary, `devsDict` :

```python
    parsedDevice = ParseDevice(data[dataPtr - devHdrLen:dataPtr + devLen])
    # Add the new device attributes (wrapped in  dictionary of appropriate identifiers) to the dictionary of devices
    merge_update(devsDict, parsedDevice.wrap_in_ids())
```

`merge_update` is a utility function which recursively adds only the
**new** parts of the nested dictionaries into `devsDict` - see later for
details.

There is also an iterator generator function, `unwrap_metricsDict`,
defined in seDataDevices.py, for when you need to "unwrap" device
attributes, for example to send them to graphite, or to save in a csv
file.

For more in depth explanations, and a few embellishments ("bells and
whistles"), read on.

----

## Background and introduction

The `ParsedDevice` class is defined in the seDataDevices.py module.  It
was written using Python 2.7 and would probably need a few minor changes
to work under Python 3.x

It began as an attempt to write a _parser_ for the messages sent from a
solareedge inverter to the solaredge website in such a way that new
devices could be *relatively* easily added to the set of devices that
can be recognised and decoded.

The approach initially followed the
proposal for table driven parsing of new devices, given in
[Issue #22 Table Driven Table driven data interpretation for new devices](https://github.com/jbuehl/solaredge/issues/22) ,
and evolved from there.

In that proposal the syntax for describing the data fields/items
embedded in a device message looks rather like a nested Python dictionary,
or something that had been read in from a json file.  A bit of thought
led to the conclusion that nested lists, rather than nested
dictionaries would be easier to work with, principally because the
ordering of the fields is somewhat important :-)  At its core, that is
what ParseDevice uses, a nested list of definitions for the fields
required to interpret a device.

After a bit more work, it became apparent that some functions were
required to apply those definitions to a block of device
data captured from solaredge website traffic. Rather than code these as
free-standing functions, the `ParseDevice` class was born, and the
functions became methods of the class.

New devices can be added to the set by subclassing `ParseDevice`, and
supplying a list of item definitions in the subclass.  The subclass by
its very nature inherits all the methods of `ParseDevice` itself,
avoiding the need to recode them.

The next addition to the way ParseDevice works was driven by
the realisation that ideally the code in the `parseDeviceData` function
in seData.py should not need to know the names of the subclasses of
`ParseDevice`.  So the `__new__` method for `ParseDevice` was written as
a sort of traffic director.  When ParseDevice is given a block of data
to parse, `ParseDevice.__new__` extracts the `seType` from the header,
and examines all its own subclasses.  Subclasses nominate the `seType` they
are designed to interpret, and if a match is found, the `ParseDevice`
constructor actually returns an instance of the subclass, rather than an
an instance of `ParseDevice` itself.  `ParseDevice` also has two options
(a minimal parse, and a maximal parse) for what to do if no subclass
has yet been defined for a particular device (aka `seType`).
Effectively, other code need only ever send a block of data to
`ParseDevice` itself, which then determines dynamically how best that
block can be parsed.

To date (May 2017) two subclasses have been defined:

1. `ParseDevice_0x0030`, which interprets the data stream from a battery,
and

2. `ParseDevice_0x0022`, which interprets a data stream including import,
export and consumption data.  I have called this *meters*, for want of
any better insight into exactly which subsystem of the solaredge
inverter is responsible for sending these `0x0022` messages.

The final *essential* components of the `ParseDevice` suite emerged so
that :

* seData.py did not have to be updated every time a new device type was
added, and
* devices that had multiple messages for the same time point (e.g.
optimisers, batteries, and "0x0022") could distinguish them.

To achieve these objectives, `devsDict` was born and `wrap_in_ids`,
`unwrap_metricDict` and `merge_update`  were developed.

During development a few other minor features were added, mostly to make
the use of `ParseDevice` less effort.  These are described later.

---
## ParseDevice class in more detail

### A `ParseDevice` is actually a dictionary

`ParseDevice` is itself a subclass of `dict`.  Once created and
initialised from a block of data, an instance of a `ParseDevice` is a
Python dictionary, which maps item names (found from the list of
definitions) to item values (extracted from the block of data sent to
`ParseDevice`).

Aside re terminology : I tend to use *item*, *field* and *device attribute*
to mean the same thing, fairly interchangeably, in this explanation and
in the comments in the Python code itself.

### The `ParseDevice.__new__` method

The underlying purpose of the `__new__` method was described in the
introduction.

The key point to be aware of is that since the actual construction of a
new instance may be delegated to a subclass, it is **imperative** that
all subclasses have their own explicit `__new__` method.  Failure to do
this results in a runtime recursion limit error!

The `__new__` method for a subclass is not complicated - see for example
`ParseDevice_0x0030.__new__` :

```python
    def __new__(cls, data, explorer=False):
        # Create a bare minimum instance of a dictionary.
        # Note that a more usual idiom would be
        # super(ParseDevice_0x0030, cls).__new__(cls), but this
        # would lead to the recursion  that we are trying to avoid!
        return super(ParseDevice, cls).__new__(cls)
```

### Defining the type of data that can be parsed

There are three attributes of `ParseDevice` (and more importantly, of
any subclass) that signal what type of data can be parsed.

For `ParseDevice` itself, these are essentially dummy placeholders :

```python
    _dev = 0xffff # dummy value, I hope.  Should be overwritten in subclasses.
    _devName = 'Unknown_device'
    _devType = '{}_{:#06x}'.format(_devName, _dev)
```

For a subclass such as `ParseDevice_0x0030` they are more meaningful :

```python
    _dev =0x0030
    _devName = 'batteries'
    _devType = '{}_{:#06x}'.format(_devName, _dev)
```

`_dev` must match the `seType` that appears at the start of the data
block that the subclass can parse.

`_devName` is an informative label used to make the `seType` more
interpretable to humans, and

`_devType` is a combination of the two that is used as part of the
complete, fully qualified "name" of any field, when, for example, it is
saved in json format or sent to graphite.

### Defining fields : `ParseDevice._defn` and `ParseDevice.parseDevTable`

`ParseDevice._defn` is the core component of the `ParseDevice`
class. It is a list of definitions of fields.

`ParseDevice` itself does not define any fields, so `_defn = []`.

In general however, each field definition in `_defn` is itself a list,
consisting of exactly 6 entries.  The 6 entries are :

1. **paramLen** - the length in bytes of the field.

2. **paramInFmt** - the format to be used to unpack the field.

   Any format that `struct.unpack` recognises can be used.
   (Note that the correct paramLen must be given - this is not checked).

   The special value "hex" is also recognised,
   in which case the value of the field is simply the raw bytes themselves.

3. **paramName** - the name of the field.

   Technically this could be anything that Python will accept as a
   dictionary key.


   But in practice it should be a string without any special characters
   or spaces, since otherwise problems occur when you send the values to
   graphite.

4. **outFormatFn** - a function to convert the parsed value
   into a more useful output format.

   Two special entries are accepted by `ParseDevice`.

   * "dateTime" is parsed into 2 field entries, "Date" and "Time", both in
     human readable format, and in the local timezone.
   * `ParseDevice.hexData` is a (staticmethod) utility function, which
     converts raw bytes into a nicely formatted human readable string
     representation.  It is mostly used in conjunction with the "hex" paramInFmt.

   `None` is also an acceptable value, in which case `str` is the
   implicit default output format function.

5. **out** - True or False, to signal whether or not this field should
   be output to csv or graphite. (Not fully implemented yet).

6. **comment** - an arbitrary string.  While `""` is acceptable, it is
   intended to contain a helpful description of the interpretation of
   the field.

To help make this clearer, here is an extract from
`ParseDevice_0x0030._defn` :

```python
    _defn = [
        # device specific fields
        #  [paramLen, paramInFmt, paramName, outFormatFn (can be None), out (to csv or graphite) True or False, comment]
        [4, 'L', "dateTime", "dateTime", False, "Seconds since the epoch"],
        [12, '12s', "batteryId", None, True, "Identifier for this battery"],
        [4, 'f', 'Vdc', None, True, "Volts"],
        ...
        [4, 'hex', 'HexConst_52', ParseDevice.hexData, False, "Unknown, constant value"],
        ...
        [2, 'H', 'BattChargingStatus', None, True, "3=>Charging, 4=>Discharging, 6=>Holding"],
        ...
        [4, 'L', 'EOut', None, True, "Wh, Energy out of battery during interval"],
    ]
```


The `ParseDevice.parseDevTable` method is responsible for parsing a
block of data using the definitions in `_defn` and storing the results
as `name : value` entries in the ParseDevice dictionary.  It is called
by `ParseDevice.__init__`.

Before beginning parsing, `parseDevTable` compares the total length of
the field definitions to the length (`devlen`) of the data block.  If
the field definitions are :

* longer --- it complains (raises an exception!).
* shorter --- it adds one final field (defined as a hex
string) to the end of the list of field definitions, to consume the
remaining bytes.

### Deriving new fields : `ParseDevice._derivn`

Sometimes more complex manipulations, such as bit shifting, might be
required to fully decode some fields in a device data block.

After a bit of contemplation, I realised that trying to design a table
driven syntax for such manipulations would, in effect, be rewriting the
Python language in a table.  Or so it seemed to me anyway.

So instead I included hooks in the code for `ParseDevice` that allow
subclasses to undertake more complex manipulations by calling Python
code.  The hooks are :

* `_derivn`,
* `setDerivationDefaults`, and
* `codeDerivations`

`_derivn` is (essentially) a cut down version of `_defn`. It is a list
of (partial) definitions for new fields that are to be calculated and
added to the `ParseDevice` dictionary, once all the data block fields
have been read and parsed.  To be precise each definition of a derived
field is a list with 4 elements, namely :

1. **paramName** - as per `_defn`
2. **paramDefault** - an initial default value for the field, typically
   `0`, `0.0`, `""` or `float("nan")`
3. **out** (to csv) True or False - as per `_defn`
4. **comment** - as per `_defn`

```python
    _derivn = [
        # [paramName, paramDefault, out (to csv) True or False, comment]
    ]
```

The `setDerivationDefaults` method is provided in `ParseDevice`, and
simply populates the `ParseDevice` (sub)class dictionary with the
default `paramName : paramDefault` entries.

The `codeDerivations` method for `ParseDevice` itself is merely an empty
stub (`pass`).  The stub should be overrriden by any subclass that
requires more complex manipulations.  It is responsible for :

* accessing values that have been extracted from the device data block
(they can be accessed as `self["inputParamName"]`),
* performing whatever manipulations are necessary to calculate the
derived_value for a "derivedParamName", and then
* replacing paramDefault value with the derived_value ( via
`self["derivedParamName"] = derived_value`).

At the moment, the `codeDerivations` methods for subclasses
`ParseDevice_0x0022` and `ParseDevice_0x0030` are also empty stubs.

#### Simple example of a derivation

However earlier iterations of `ParseDevice_0x0022` did utilise the
`_derivn`, and `codeDerivations` approach successfully, so it has been
(somewhat) tested.  As an example of the approach, here is an extract of
the relevant code from an earlier (since deleted) version of
`ParseDevice_0x0022`


```python
    _defn = [
        # device specific fields
        #  [paramLen, paramInFmt, paramName, outFormatFn (can be None), out (to csv or graphite) True or False, comment]
        [4, 'L', "dateTime", "dateTime", False, "Seconds since epoch"],
        [1, 'b', "recType", None, True, "record Type, determines the interpretation of later fields" +sp+ "5=Lifetime, 3=Importing?, 7=Battery?, 8=?, 9=2Load?"],
        [1, 'b', "intervalData", None, True, "1=only interval data has been reported, 0=lifetime data reported as well"],

        [4, 'L', 'TotalE2Grid', None, True, "Wh, Lifetime Energy exported to grid (*provided* lifetime flag is set)" +
        ...
        [4, 'L', 'E2X', None, True, "Wh, Energy to X during the interval"],
        [4, 'L', 'EfromX', None, True, "Wh, Energy in from X during interval ?"],
        [4, 'f', 'P2X', None, True, "W, Power output to X"],
        [4, 'f', 'PfromX', None, True, "W, Power input from X?"],
    ]

    _derivn = [
        # [paramName, paramDefault, out (to csv) True or False, comment]

        # recType=5 and (only) intervalData=0 (False) is Grid export / import
        ["0_5_TotalE2Grid", "nan", True, "Wh, Total lifetime export to grid" + sp + "matches SE LCD panel value"],
        ...
        ["0_5_E2X", "nan", True, "Wh, Energy exported to grid during interval" + sp + "whenever TotalE2Grid is static, E2X=0"],
        ["0_5_EfromX", "nan", True, "Wh, Energy imported from grid during interval" + sp + "whenever TotalEfromGrid is static, EfromX=0"],
        ["0_5_P2X", "nan", True, "W, Power to grid (at end of?) interval" + sp + "whenever TotalE2Grid is static, P2X=0"],
        ["0_5_PfromX", "nan", True, "W, Power from grid (at end of?) interval" + sp + "whenever TotalEfromGrid is static, PfromX=0"],
        ...
    ]

    def codeDerivations(self):
        names = ["TotalE2Grid", ..., "E2X", "EfromX", "P2X", "PfromX"]
        for name in names:
            rt = self["recType"]
            idt = self["intervalData"]
            self["{}_{}_{}".format(idt, rt, name)] = self[name]
```

In this example the *derivation* consisted of copying the raw value,
read from the data block, into a new field with a similar name, but prefixed
by the value of two other fields (`intervalData` and `recType`) - so if
for example `self["intervalData"] == 0` and `self["recType"] == 5`, then
the value of `self["0_5_PfromX"]` was changed from the default(`"nan"`)
to whatever value was provided for `self["PfromX]` in the device data
block.

### `ParseDevice.__init__` and the explore argument

The `ParseDevice.__init__` method, inherited by all subclasses, is quite
simple :

```python
    def __init__(self, data, explorer=False):
        self.parseDevTable(data)
        self.setDerivationDefaults()
        self.codeDerivations()
        self.checkHypotheses()
```

Notice that the full signature of the method includes two arguments :

* `data` is the message data to be decoded, and
* the `explorer` argument is a flag to instruct `ParseDevice` what to do
 when it encounters an `seType` which has no subclass ready to parse it.

When `explorer` is :

* `False`, that instructs `ParseDevice` to do a minimal parse  - the
complete block, less the standard header, is returned as a prettily
formatted  hexadecimal string representation.  This should be the
production setting.
* `True`, the parsing is delegated to a special subclass
(`ParseDevice_Explorer`), which parses every pair and quadruple of bytes
in multiple ways.  Most resultant "fields" will be invalid, or contain
nonsense values, but this can be a useful exploratory step when
trying to decipher a new device / `seType`.

Subclasses do not use the `explorer` argument, since it only makes
sense for the `ParseDevice.__new__` method (but it causes potential
signature incompatibility problems if it does not exist, so include it
anyway if you do code an explicit `__init__` for a subclass instead of
just inheriting `ParseDevice.__init__`).

To find out about the `checkHypotheses` method, see later, under "bells
and whistles".

### `ParseDevice.wrap_in_ids`

The purpose of this method was described earlier, in the brief overview
section towards the top of this document.

It wraps the `ParseDevice` (or subclass) dictionary inside a
*nested dictionary* structure, so that different device types
(inverters, batteries, optimisers etc.), and different instances of
specific devices (optimiser1, optimiser2 etc) can be distinguished.

The highest level wrapping should always be `self._devType`, but after
that, subclasses can provide whatever additional wrappings they need
to uniquely identify the specific device (inverter, battery, optimiser,
etc).

### `merge_update`

`merge_update` is a utility function added to seData.py to recursively
add **only** the "new" parts of the nested dictionaries into `devsDict`.

In plain words, it exists to avoid a problem that would occur if you
simply used `devsDict.update(parsedDevice.wrap_in_ids())`, namely that
later batteries (or optimisers, etc) would overwrite earlier ones.

To illustrate, consider the following example :

```python
import pprint as pp

from seDataDevices import merge_update
print "\nA demonstration of what merge_update does\n"

wrappedDict1 = {"device1" : {"seId1" : {"otherId1" : {"Date" : "a date", "Fred" : "fred1"}}}}
wrappedDict2 = {"device1" : {"seId2" : {"otherId2" : {"Date" : "a date", "Fred" : "fred2"}}}}

print "Here are wrappedDict1, and wrappedDict2"
pp.pprint(wrappedDict1)
pp.pprint(wrappedDict2)

print "\nUpdating devsDict the naive way, using dict.update, overwrites seId1 with seId2"

devsDict = {}
devsDict.update(wrappedDict1)
devsDict.update(wrappedDict2)

pp.pprint(devsDict)

print "\nUpdating devsDict using merge_update retains both seId1 and seId2"

devsDict = {}
merge_update(devsDict, wrappedDict1)
merge_update(devsDict, wrappedDict2)

pp.pprint(devsDict)
```

which produces the following output :

```
A demonstration of what merge_update does

Here are wrappedDict1, and wrappedDict2
{'device1': {'seId1': {'otherId1': {'Date': 'a date', 'Fred': 'fred1'}}}}
{'device1': {'seId2': {'otherId2': {'Date': 'a date', 'Fred': 'fred2'}}}}

Updating devsDict the naive way, using dict.update, overwrites seId1 with seId2
{'device1': {'seId2': {'otherId2': {'Date': 'a date', 'Fred': 'fred2'}}}}

Updating devsDict using merge_update retains both seId1 and seId2
{'device1': {'seId1': {'otherId1': {'Date': 'a date', 'Fred': 'fred1'}},
             'seId2': {'otherId2': {'Date': 'a date', 'Fred': 'fred2'}}}}
```


### Unwrapping a nested dictionary, the `unwrap_metricsDict` iterator

`unwrap_metricsDict` is an iterator generator function, defined in
seDataDevices.py, for when you need to "unwrap" device
attributes, for example to send them to graphite, or to save in a csv
file.

It can be thought of as an inverse (of sorts) to the
`ParseDevice.wrap_in_ids` method.

It will work equally well on a dictionary produced by `json.loads`
(where the source json was created from a parsed device dictionary).

It unwraps recursively, so that the depth of nesting is essentially
arbitrary, and indeed can vary from one device type to another.

To illustrate what `unwrap_metricsDict` does, consider the following
example, which continues on from the `merge_update` example
above:

```python
from seDataDevices import unwrap_metricsDict
print "\nA demonstration of what unwrap_metricsDict does"

i = 0
for baseName, devAttrs in unwrap_metricsDict(devsDict):
    i += 1
    print "\nbaseName {} is ".format(i), baseName, "\nand devAttrs are "
    pp.pprint(devAttrs)
```

It produces the following output :

```
A demonstration of what unwrap_metricsDict does

baseName 1 is  device1.seId1.otherId1
and devAttrs are
{'Date': 'a date', 'Fred': 'fred1'}

baseName 2 is  device1.seId2.otherId2
and devAttrs are
{'Date': 'a date', 'Fred': 'fred2'}
```

An implementation detail is that `"Date"` **must** be one of the field
names (i.e. a dictionary keys) in the deepest level of the
*nested dictionaries*, because that is how the algorithm knows it has
reached the lowest level of the nested dictionaries.

----

## Bells and whistles (useful but non-essential parts of `ParseDevice`)

### `_hypotheses` and `ParseDevice.checkHypotheses`

During the process of deciphering new devices, I often came across
values that appeared to be constant.  To be able to confirm (or deny)
that they were constant during extended runs of semonitor, I added the
concept of hypotheses to `ParseDevice`.

`_hypotheses` is a list of strings which contain valid Python
expressions, which evaluate to `True` or `False`.  The `checkHypotheses`
method, invoked as the last step in the `__init__` method, simply
evaluates these expressions, and logs any situation where they evaluate
to `False`.  An example (taken from `ParseDevice_0x0022`) may make this
clearer :

```python
    _hypotheses = [
        "self['AlwaysZero_off10_int2'] == 0",
        "self['AlwaysZero_off18_int2'] == 0",
        "self['AlwaysZero_off26_int2'] == 0",
        "self['AlwaysZero_off34_int2'] == 0",
    ]
```


### Documenting device fields - the `ParseDevice.itemDefs` method.

Initially, explanations and comments about fields that had been
deciphered were kept (rather haphazardly) as Python comments in the code
for subclasses of `ParseDevice`.  After a few iterations, I decided to
make the field definitions (entries in `ParseDevice._defn`) self
documenting by incorporating an explicit **comment** in each
definition.

The `itemDefs` method returns a prettily formatted report on all the
the item definitions parsed by `ParseDevice`, and its subclasses.

It can be used quite simply :

```python
from seDataDevices import ParseDevice
print ParseDevice.itemDefs()
```

This is a small extract of the resultant output :

```
...
ParseDevice_0x0030 / batteries_0x0030 parses data blocks with seType = 0x0030.
================================================================================
Items are:
Byte (Length)   Word   | Item Name
                        : Meaning

____ (______)   ______ | _________________________
                        : ________________________________________

0    (  4   )   0.0    | dateTime
                        : Seconds since the epoch

4    (  12  )   1.0    | batteryId
                        : Identifier for this battery

16   (  4   )   4.0    | Vdc
                        : Volts

20   (  4   )   5.0    | Idc
                        : Amps

24   (  4   )   6.0    | BattCapacityNom
                        : Wh, Nameplate Energy Capacity

28   (  4   )   7.0    | BattCapacityActual
                        : Wh, Actual Battery Capacity now

32   (  4   )   8.0    | BattCharge
                        : Wh, Energy Stored now
...
```

Of course, it can also be used for a specific subclass as well.

### Other `ParseDevice` methods

`ParseDevice` "acquired" a few other methods, mostly for convenience.
 By and large they were utility functions, which I copied from elsewhere
 in the semonitor project, and converted to methods, to avoid
 complications (such as circular references) when I tried to import them
from the original modules.  See the code for further details.

----

## Subclasses of `ParseDevice`

To date (May 2017) two subclasses of `ParseDevice` have been written for
specific device types (for `seType`s 0x0030, and 0x0022), as well as one
*special* subclass that can do a *maximal* parse of any device type.

### `ParseDevice_0x0030` - batteries

`seType` 0x0030 relays information about the status of a battery.  Use
`print ParseDevice_0x0030.itemDefs()` to obtain uptodate documentation
about the fields and their interpretation.

The field interpretations were deciphered by comparing values produced
by (early versions of) `ParseDevice_0x0030` with information from the
LCD display on a solaredge inverter.

To be precise, it is a SE6000 inverter, with a Tesla Powerwall 1 battery
attached.  Possibly other solaredge inverter / battery hardware or
software version combinations may require further work - but since I
have only this one system to work on, I can't do that :-)

### `ParseDevice_0x0022` - import, export and consumption data

`seType` 0x0022 relays an assortment of summary information about the
status of a solaredge system.  Amongst the fields are ones which report
current interval import, export and consumption data.

For want of a better name, I have called an 0x0022 message a "meters"
message.

Use `print ParseDevice_0x0022.itemDefs()` to obtain uptodate
documentation about the fields and their interpretation.

The trickiest part of deciphering the 0x0022 data block was discovering
that early in the data block, there is a record type field.  The
interpretation of subsequent fields changes, depending upon the value of
the record type.  Full details are available in the `itemDefs()` report.

Field interpretations were deciphered by comparing values against
information that can be downloaded in csv format from the solaredge
website.  Using graphite to look at the behaviour of field values over
the course of a day or two was a quick way of figuring out what type of
solareedge website data to compare against.

For some fields (eg energy into the battery - `E2X` when `recType` = 7)
it was also possible to check against information from another `seType`.
There are occasionally very slight value differences (eg 1 or 2 Wh), or
timing differences (eg PV production beginning one time slot earlier or
later) when exact numerical comparisons are made this way, but nothing
that is perceptible at the level of a graphite graph, so I am reasonably
comfortable that the interpretations are correct.

There do remain a couple of fields which contain data with apparently
significant values that I have been unable to decipher so far.  In
addition there are a number of constant "flag" values whose meaning and
use is as yet unknown.

### `ParseDevice_Explorer` - parse almost anything, lots of ways

As explained earlier, `ParseDevice_Explorer` is a *special* subclass,
which can parse almost any device type.  It simply works through the
data block, 2 bytes at a time, trying multiple parsings for each
pair and quadruple of bytes. Most "fields" will be invalid, or contain
values which are obviously nonsense, but it can be a useful first step
towards developing a tailored subclass parser for a new `seType`.

The *almost* in "almost any device" arises because `ParseDevice.__new__`
(and hence all subclasses derived from it, including
`ParseDevice_Explorer`) assumes that **all** device types include a
standard header which can be decoded as follows

```python
(seType, seId, devLen) = struct.unpack("<HLH", data[0:devHdrLen])
```

There may be a few rare device messages with a different header (I
believe I have read that 0x0018 may be one), in which case
`ParseDevice_Explorer` will most likely fail (for example, it will
probably not know the correct length, `devlen`, for the data block!).

If the correct header is known, this could be corrected by appropriate
amendments in the subclass's own  `__new__` method.

----

## An approach to deciphering the fields for a new device

This is my *recipe* for deciphering a new device type using `ParseDevice`.
I will describe it sequentially, but in real life it is iterative, and
involves trial and (usually quite a lot of) error.

1. Capture a day or two's worth of traffic into a pcap file using
tcpdump.
2. Process the pcap file using semonitor.py, with
`ParseDevice(data, explorer=True)`, and save the json output.
3. Convert the json output to csv, and (beginning from the start of the
data block) eliminate parsings which are invalid, or contain values
which are clearly nonsense.
4. Draft a new subclass, specific to the `seType` with a list of field
definitions which use a plausible `struct.unpack` format.  Use the
special format "hex" if necessary to (temporarily) jump over sections of
the data block which make little sense. At a minimum you must supply:
   * `_dev` (the `seType` to be parsed)
   * `_devName` (an informative name)
   * `_devType` (I recommend `_devType = '{}_{:#06x}'.format(_devName, _dev)`
   and
   * `_defn` (the list of field definitions)
5. Run semonitor.py over the pcap file again (you may as well set
`ParseDevice(data, explorer=False)` once a draft subclass exists), save
the json output, convert to csv, and start to look for values which are
recognisable. Obvious hints include:
   * Interval Power values tend to be larger than Energy ones!
   * Total lifetime values are even larger!
6. Try sending the information to graphite, and look at the behaviour
over time. Obvious hints include :
   * PV production only happens during the day
   * Consumption happens day and night.
   * Batteries charge (usually in the morning) before they discharge
   (usually in the evening, or when it becomes cloudy)
   * System production is less than PV production when a battery is
   charging, and greater than PV production when the battery is
   discharging.
   * Import starts when system production falls below consumption,
   export is the reverse
   * ...
7. Update the subclass definition (**make sure** to update the comment
part of the field definitions to record deductions, evidence,
conjectures etc as you proceed), and repeat steps 5 and 6.
8. Try, try and try again.
9. When you feel you are getting close, try running
`tcpdump | semonitor.py | tee "ajsonfile" | se2graphite` (with
appropriate runtime parameters) for a few days, to validate the
interpretations.

The early steps (2. and 3.) could be replaced or supplemented by using
Wireshark to explore the pcap file as well.

Good luck!

----
