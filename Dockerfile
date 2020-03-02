FROM ubuntu:18.04 as base

RUN apt-get update && \
    apt-get install -y dumb-init python3 python3-distutils && \
    groupadd -g 1000 datastream && \
    useradd -u 1000 -g 1000 -m datastream && \
    apt-get clean -y && \
    find /var/lib/apt/lists -type f -delete

FROM base as build

RUN apt-get update && \
    apt-get install -y build-essential python3-pip

WORKDIR /opt/datastream

RUN chown datastream:datastream /opt/datastream

USER 1000
RUN pip3 install --user pipenv
ENV LC_ALL C.UTF-8
ENV LANG C.UTF-8
COPY Pipfile Pipfile.lock /opt/datastream/
RUN /home/datastream/.local/bin/pipenv install

FROM base as prod

ENV LC_ALL C.UTF-8
ENV PYTHONUNBUFFERED 1

USER 1000

WORKDIR /opt/datastream

COPY --from=build /opt/datastream /opt/datastream
COPY --from=build /home/datastream/ /home/datastream/
COPY datastream-to-influxdb.py /opt/datastream

USER 1000
ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["/home/datastream/.local/bin/pipenv run /opt/datastream/datastream-to-influxdb.py"]
