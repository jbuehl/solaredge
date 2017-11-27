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
        return str(k).replace("\x00", '').replace(" ", "_").replace(
            "devices", "")

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

