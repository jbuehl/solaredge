# Running semonitor in docker

semonitor can be run within a Docker container. This provides isolation from
other processes by running it in a containerized environment. This is not an
in-depth tutorial on Docker; for background on Docker or containers, see
[docker.com][docker].

This guide is not comprehensive; it only lists the most basic steps.


## Building the container

Building the container is only needed if the official one is not sufficient,
or when developing on semonitor.

To build the image, the following can be used, where `ISSUE-123` is just used
as an example. The same tag is reused later.

The version is taken from the git tags. As `.git` is not part of the build
context, it is passed in as a build argument; without it, the version is
`0+unknown`.

```sh
docker image build \
    --file 'Containerfile' \
    --build-arg "VERSION=$(pipx run setuptools-scm)" \
    --rm \
    --tag 'semonitor:ISSUE-123' \
    './'
```


## Running tests

The tests are not included in the container image, so we volume mount them to
make them available to the installed semonitor application. As there is no
source in the image, the tests run the semonitor that is installed in it.

```sh
docker container run \
    --interactive \
    --rm \
    --tty \
    --volume "$(pwd)/test:/usr/local/src/semonitor/test" \
    'semonitor:ISSUE-123' \
    './test/test.sh'
```


## Running serial device

Running semonitor on a serial device using the official latest image can
be done as follows.

```sh
docker container run \
    --device '/dev/solaredge0:/dev/ttyUSB0' \
    --interactive \
    --rm \
    --tty \
    --volume "$(pwd)/semonitor_logs/:/semonitor/" \
    'ghcr.io/jbuehl/solaredge:latest' \
        -a \
        -b 115200 \
        -m \
        -o "/semonitor/json/__date__.json" \
        -r "/semonitor/rec/__date__.rec" \
        -s '1234567' \
        -t 4 \
        '/dev/ttyUSB0'
```

To ensure semonitor can accurately set the inverter's clock, it first waits
for a valid system time when it reads from a serial device. By default,
anything older than the image is invalid; override it by setting
`SE_START_EPOCH` to a UNIX epoch or an ISO 8601 date and time, for example:

```sh
--env 'SE_START_EPOCH=2024-01-01'
--env 'SE_START_EPOCH=2024-01-01T23:01:02'
--env 'SE_START_EPOCH=1704067200'
```

It gives up after `SE_START_TIMEOUT` seconds, 60 by default.


## Using compose

It is also possible to run the container using `docker compose`. Here is an
example. The device used is a udev-symlinked serial-to-USB adapter with
the appropriate permissions.

```yaml
networks:
  semonitor: {}

volumes:
  semonitor:

services:
  semonitor:
    image: ghcr.io/jbuehl/solaredge:master
    cap_drop:
      - all
    ulimits:
      nproc: 64
      nofile:
        soft: 4194304
        hard: 16777216
    devices:
      - /dev/solaredge:/dev/ttyUSB0
    env_file:
      - common.env
    volumes:
      - semonitor:/var/lib/semonitor:rw
    networks:
      - semonitor
    expose:
      - "80/tcp"
      - "22221-22222/tcp"
    command: >-
      -a -b 115200
      -m
      -n
      -o /var/lib/semonitor/json/__date__.json
      -r /var/lib/semonitor/rec/__date__.rec
      -s 1234567
      -t 4 /dev/ttyUSB0
    restart: unless-stopped
```

[docker]: https://www.docker.com/
