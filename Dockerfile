FROM alpine

COPY requirements.txt /
RUN apk --no-cache add ca-certificates dumb-init python3 py3-openssl \
    && pip3 install -r /requirements.txt \
    && rm /requirements.txt \
    && addgroup -g 500 datastream \
    && adduser -G datastream -u 500 -D datastream

COPY datastream-to-influxdb.py /bin/

USER 500
ENV PYTHONUNBUFFERED 1

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["/bin/datastream-to-influxdb.py"]
