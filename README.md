# plattform-akamai-influxdb

Program to fetch aggregate data from Akamai datastream and add it to influxdb.

## Running

You need to create an Akamai api user with read access to datastream.

To run the program needs the following environment variables set

 * ```BASE_URL``` - The Akamai api user base URL
 * ```ACCESS_TOKEN``` - The Akamai api user access token
 * ```CLIENT_SECRET``` - The Akamai api user client secret
 * ```CLIENT_TOKEN``` - The Akamai api user client token
 * ```INFLUXDB_HOST``` - The influxdb hostname to send data to
 * ```INFLUXDB_PORT``` - The influxdb port to send data to, defaults to 8086
 * ```INFLUXDB_DATABASE``` - The influxdb database
 * ```INFLUXDB_USERNAME``` - The influxdb username
 * ```INFLUXDB_PASSWORD``` - The influxdb password
 * ```STREAMS``` - A comma separated list of streamid=hostname which list the streams to  get data from and which hostname to add to the tags

## Running in kubernetes

See [k8s-deployment-example.yaml].  You need to fill in credentials in the 
secret, as well as replace ```INFLUXDB_HOST``` and ```STREAMS``` environment
values.
