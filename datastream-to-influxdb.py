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
        # avoid other modules from logging too much
        level=logging.WARN,
    )
    logging.getLogger("__main__").setLevel(log_level)

    log = structlog.get_logger()
    return log

class DataStream:
    def __init__(self, session, log, influx_client, datastream_url, hostname):
        self.session = session
        self.log = log
        self.influx_client = influx_client
        self.datastream_url = datastream_url
        self.hostname = hostname
        self.start = datetime.datetime.utcnow() - datetime.timedelta(minutes=6)
        self.end = datetime.datetime.utcnow() - datetime.timedelta(minutes=5)
        self.wait = None
        self.wait_time = None
        self.retries = None
        self.page_size = os.environ.get('PAGE_SIZE', '1000')
        self.retry_no_content = os.environ.get('RETRY_204') is not None

    def _update_retries(self):
        if self.wait is None:
            self.retries = 3
            self.wait = 5
            self.wait_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=5)
        else:
            if self.retries > 0:
                self.wait = self.wait * 3
                self.wait_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=self.wait)
                self.retries -= 1
            else:
                self.wait = None
                self.retries = None
                self._update_start_end()

    def _update_start_end(self):
        self.start = self.end
        self.end = self.start + datetime.timedelta(minutes=1)

    def should_wait(self):
        now = datetime.datetime.utcnow()
        self.log.debug("checking wait", wait=self.wait, retries=self.retries, hostname=self.hostname)

        if self.wait is not None:
            return now < self.wait_time

        return (now - self.end).seconds < 300

    def get_metrics(self):
        metrics = '2xx,3xx,4xx,5xx,edgeResponseTime,originResponseTime,requestsPerSecond,bytesPerSecond,numCacheHit,numCacheMiss,offloadRate'
        influxdb_data = []
        page = 0
        done = False
        while not done:
            try:
                fetch_parameters={
                    'start': self.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    'end': self.end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    'page': page,
                    'size': self.page_size,
                    'aggregateMetric': metrics
                    }
                self.log.debug("Fetching data", datastream_url=self.datastream_url, params=fetch_parameters, hostname=self.hostname)
                result = self.session.get(self.datastream_url, params=fetch_parameters, timeout=42)
            except Exception as e:
                self.log.error("Error getting datastream data %s", e, exc_info=True, hostname=self.hostname)
                self._update_retries()
                return
            if result.status_code == 204:
                self.log.info("Got 204 no content", body=result.text, hostname=self.hostname)
                if self.retry_no_content:
                    self._update_retries()
                    return
                else:
                    done = True
            elif result.status_code != 200:
                self.log.error("Error getting datastream data", status_code=result.status_code, return_text=result.text, hostname=self.hostname)
                self._update_retries()
                return
            else:
                self.log.debug("got data, size %d", len(result.content), status_code=result.status_code, hostname=self.hostname)
                try:
                    data = result.json()
                except Exception as e:
                    self.log.error("Error decoding json data", status_code=result.status_code, return_text=result.text, hostname=self.hostname)
                    self._update_retries()
                    return
                for entry in data['data']:
                    m = {}
                    m['tags'] = {'hostname': self.hostname}
                    m['measurement'] = 'aggregate'
                    m['time'] = entry['startTime']
                    m['fields'] = {}
                    for measurement in metrics.split(','):
                        if measurement in entry:
                            m['fields'][measurement] = entry[measurement]
                    influxdb_data.append(m)
                try:
                    if not self.influx_client.write_points(influxdb_data):
                        self.log.error("Error writing to influxdb", hostname=self.hostname)
                        return
                except Exception as e:
                    self.log.error("Error writing to influxdb", exc_info=True)
                    return
                page += 1
                if page >= data['metadata']['pageCount']:
                    done = True

        self._update_start_end()


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
    datastreams = []
    for datastream_url, hostname in get_datastreams():
        datastreams.append(DataStream(session, log, influx_client, datastream_url, hostname))
    while True:
        start = datetime.datetime.utcnow()
        for datastream in datastreams:
            if not datastream.should_wait():
                datastream.get_metrics()

        now = datetime.datetime.utcnow()
        if (now - start).seconds < 60:
            time.sleep((now - start).seconds)


if __name__ == "__main__":
    log = get_log()
    session, influx_client = setup()
    main(log, session, influx_client)
