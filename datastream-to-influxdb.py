#!/usr/bin/env python3

from influxdb import InfluxDBClient
from akamai.edgegrid import EdgeGridAuth
import datetime
import logging
import requests
from urllib.parse import urljoin
import os
import structlog
import sys
import time

log_levels = {
    'debug': 20,
    'info': 30,
    'warning': 40,
    'error': 50,
    'critical': 60
}


def server_log(logger, method_name, event_dict):
    event_dict['msg'] = event_dict.pop('event')
    level = event_dict.pop('level')
    event_dict['logLevel'] = level.upper()
    event_dict['level'] = log_levels[level]

    return event_dict


def get_log():
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            server_log,
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    if 'DEBUG' in os.environ:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    log = structlog.get_logger()
    return log


def get_metrics(log, start, end, session, influx_client, datastream_url, hostname, retries=2):
    if retries <= 0:
        return
    metrics = '2xx,3xx,4xx,5xx,edgeResponseTime,originResponseTime,requestsPerSecond,bytesPerSecond,numCacheHit,numCacheMiss,offloadRate'
    influxdb_data = []
    page = 0
    done = False
    while not done:
        try:
            result = session.get(datastream_url, params={
                'start': start, 'end': end, 'page': page, 'size': 1000, 'aggregateMetric': metrics})
        except Exception as e:
            log.error("Error getting datastream data {}".format(
                e), exc_info=True)
            time.sleep(1)
            return get_metrics(log, start, end, session, influx_client, datastream_url, hostname, retries - 1)
        if not result.ok:
            log.error("Error getting datastream data: {}".format(result.text))
            time.sleep(1)
            return get_metrics(log, start, end, session, influx_client, datastream_url, hostname, retries - 1)
        try:
            data = result.json()
        except Exception as e:
            log.error("Error getting datastream data {}".format(
                e), exc_info=True)
            return get_metrics(log, start, end, session, influx_client, datastream_url, hostname, retries - 1)
        for entry in data['data']:
            m = {}
            m['tags'] = {'hostname': hostname}
            m['measurement'] = 'aggregate'
            m['time'] = entry['startTime']
            m['fields'] = {}
            for measurement in metrics.split(','):
                if measurement in entry:
                    m['fields'][measurement] = entry[measurement]
            influxdb_data.append(m)
        try:
            if not influx_client.write_points(influxdb_data):
                log.error("Error writing to influxdb")
                return
        except Exception as e:
            log.error("Error writing to influxdb: {}".format(e), exc_info=True)
            return
        page += 1
        if page >= data['metadata']['pageCount']:
            done = True


def setup():
    port = 8086
    if 'INFLUXDB_PORT' in os.environ:
        port = int(os.environ['INFLUXDB_PORT'])
    influx_client = InfluxDBClient(
        host=os.environ['INFLUXDB_HOST'],
        port=port,
        username=os.environ['INFLUXDB_USERNAME'],
        password=os.environ['INFLUXDB_PASSWORD'],
        database=os.environ['INFLUXDB_DATABASE'],
        ssl=True, verify_ssl=True
    )
    session = requests.Session()
    session.auth = EdgeGridAuth(
        client_token=os.environ['CLIENT_TOKEN'],
        client_secret=os.environ['CLIENT_SECRET'],
        access_token=os.environ['ACCESS_TOKEN']
    )
    return (session, influx_client)


def get_datastreams():
    baseurl = os.environ['BASE_URL']
    streams = os.environ['STREAMS'].split(",")
    for stream in streams:
        stream_id, hostname = stream.split("=")
        datastream_url = urljoin(baseurl,
                                 '/datastream-pull-api/v1/streams/{}/aggregate-logs'.format(stream_id))
        yield (datastream_url, hostname)


def main(log, session, influx_client):
    start = datetime.datetime.utcnow() - datetime.timedelta(minutes=2)
    end = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
    while True:
        start_time = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_time = end.strftime("%Y-%m-%dT%H:%M:%SZ")
        for datastream_url, hostname in get_datastreams():
            log.info("Fetching logs for {} start={} end={}".format(hostname,
                                                                   start_time, end_time))
            get_metrics(log, start_time, end_time,
                        session, influx_client,
                        datastream_url, hostname)
        start = end
        end = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
        if(end < start):
            time.sleep(60)
        end = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)


if __name__ == "__main__":
    log = get_log()
    session, influx_client = setup()
    main(log, session, influx_client)
