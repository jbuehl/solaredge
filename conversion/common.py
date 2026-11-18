import sys
from pathlib import Path


def open_input(args):
    """
    Open the input of a conversion script.

    The input is the file named by the first argument, or stdin when there is none. A file that was asked for but
    cannot be opened is an error, it must not silently turn into reading stdin.

    Args:
        args: The positional command line arguments. The first one, if there is one, names the input file.

    Returns:
        The open input file, or sys.stdin when there is no argument.

    Raises:
        SystemExit: If the named file cannot be opened, with the error written to stderr and exit status 1.
    """
    if not args:
        return sys.stdin
    try:
        return Path(args[0]).open()
    except OSError as ex:
        sys.exit(f"{sys.argv[0]}: {ex}")


def unwrap_metricsDict(mydict):
    """
    An iterator/generator function to "flatten" (aka unwrap) the attributes stored in the parsed device dictionaries,
    after they have been wrapped in the device type and device id identifiers. The inverse (sort of) to the
    ParseDevice.wrap_in_ids method.

    Will work equally well on a json.loads dictionary (where the JSON was created from a parsed device dictionary).

    :param mydict: A nested set of dictionaries, the deepest level of which records the attributes for a device. "Date"
     must be one of those device attributes, because that is how the algorithm knows it has reached the bottom of the
     nest.

    :return: A Graphite-style structured name for the device instance, and a {name: value} dictionary of its attributes.
    """

    def nice(k):
        # Remove characters which give Graphite or open (a file) problems.
        # Also remove an extra level of naming (devices) that I don't really need anymore.
        # TODO: tidy up and delete the removal of "devices" when testing is over.
        return (
            str(k).replace("\x00", "").replace(" ", "_").replace("devices", "")
        )

    for k, v in mydict.items():
        if "Date" in v:
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
                    yield f"{nice(k)}.{nice(k2)}", v2
