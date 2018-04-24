#!/usr/bin/env python

# Amateur radio (HAM) repeater aggregator and converter
# Copyright (C) 2018 Pelle Sepp Florens Jansen PA8Q
#
# This file is part of RepeaterConverter
#
# RepeaterConverter is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# RepeaterConverter is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with RepeaterConverter.  If not, see <http://www.gnu.org/licenses/>.

from bs4 import BeautifulSoup
import requests
import time
import datetime
import copy
import re
import logging
import pprint
import csv
import json
import random

#Setup logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger('RepeaterConverter')

# get a prettyprinter
pp = pprint.PrettyPrinter(indent=2)
pprint = pp.pprint

#kHz and MHz defenitions for readability
kHz = pow(10, 3)
MHz = pow(10, 6)


class Source(object):
    """ Main data source class,
    only supports hamnieuws for now,
    but can be modified to include more sources if required
    """
    #Shift
    shift_28 = -100 * kHz #-100kHz
    shift_144 = -600 * kHz #-600kHz
    shift_430 = 1600 * kHz #+1.6MHz
    shift_1298 = -28 * MHz #-28MHz

    class Hamnieuws(object):
        """ Hamnieuws data source
        """
        #source URL's
        url_28 = 'https://www.hamnieuws.nl/repeaters/hf-repeaters-28-mhz/'
        url_144 = 'https://www.hamnieuws.nl/repeaters/vhf-repeaters-144-mhz/'
        url_430 = 'https://www.hamnieuws.nl/repeaters/uhf-repeaters-430-mhz/'
        url_1298 = 'https://www.hamnieuws.nl/repeaters/uhf-repeaters-1298-mhz/'

        #Class of the table containing data
        tableclass = "avia-table"

        #Indexes (columns)
        COLUMNS = ("Callsign", "Location", "Frequency", "CTCSS")
        CALLSIGN_IDX = 0
        LOCATION_IDX = 1
        FREQUENCY_IDX = 2
        CTCSS_IDX = 3

        def __init__(self, parser="lxml"):
            self.parser = parser

        def getRepeaters(self, freq):
            """ Get all repeaters for a specific frequency
            """
            #Get the right URL and shift for each repeater
            if freq == 28:
                soup = BeautifulSoup(requests.get(self.url_28).text, self.parser)
                return self._data_to_table(self._get_data(soup), Source.shift_28)

            elif freq == 144:
                soup = BeautifulSoup(requests.get(self.url_144).text, self.parser)
                return self._data_to_table(self._get_data(soup), Source.shift_144)

            elif freq == 430:
                soup = BeautifulSoup(requests.get(self.url_430).text, self.parser)
                return self._data_to_table(self._get_data(soup), Source.shift_430)

            elif freq == 1298:
                soup = BeautifulSoup(requests.get(self.url_1298).text, self.parser)
                return self._data_to_table(self._get_data(soup), Source.shift_1298)
            else:
                log.error("Invalid frequency group: {} ! Use 28, 144, 430 or 1298".format(freq))


        def _get_data(self, soup):
            """ Parse the html page to get all table rows
            """
            # Result list
            data = []

            #Find the table with the right class, then get all rows out of said table.
            table = soup.find('table', {"class": self.tableclass})
            table_body = table.find('tbody')
            table_rows = table_body.find_all('tr')

            # Iterate over the rows and shove them up the result list if it is not empty
            for row in table_rows:
                item = [element.text.strip() for element in row.find_all('td')]
                if item:
                    data.append(tuple(item))

            #return the result as a tuple to prevent accidental mutation
            return tuple(data)

        def _data_to_table (self, data, shift):
            """ Gets the repeater data out of the table rows
            """
            ret = []
            for row in data:
                try:
                    #Clean up the ctcss values
                    ctcss = row[self.CTCSS_IDX].replace('-','').replace(' ', '').strip()

                    #Build the final output dictonary
                    out = {"Callsign": row[self.CALLSIGN_IDX],
                           "Location": row[self.LOCATION_IDX],
                           "Frequency": row[self.FREQUENCY_IDX],
                           "TX_Frequency": 0.0,
                           "Shift": shift,
                           "CTCSS": ctcss,}
                except Exception as e:
                    log.warn("Failed to convert row: {}: {}".format(row, e))
                    continue

                #TODO: The 1298 in/out frequency dance

                #Calculate the transmit frequency
                try:
                    f_frequency = float(out["Frequency"]) * MHz
                    out["TX_Frequency"] = f_frequency + shift
                except Exception as e:
                    log.warn("Failed to convert frequency for {}: {}".format(out["Frequency"], e))

                #Save the result
                ret.append(out)

            #Return the result as a tuple to prevent accidental mutations.
            return tuple(ret)



class Output(object):
    """ Converts a table to all supported output file types
    """
    def __init__(self, table):
        self.table = table

    def write_csv (self, csvfile):
        """ Writes all data into a standard CSV file
        """
        with open(csvfile, 'w') as f:
            w = csv.DictWriter(f, self.table[0].keys())
            w.writeheader()
            w.writerows(self.table)

    def write_chirp_csv (self, csvfile, shiftdir=''):
        outrows = []
        counter = 0

        #Create all chirp CSV data for each repeater
        for row in self.table:
            ctcss = row["CTCSS"]
            #Try to convert the ctcss to a float. If that fails, it is not a number
            if ctcss:
                try:
                    float(ctcss)
                except:
                    log.warn("Something wrong with CTCSS '{}' of repeater {}".format(ctcss, row))
                    ctcss = '82.5'

            out = {
                "Location": counter,
                "Name": row['Callsign'],
                "Frequency": row['Frequency'],
                "Duplex": shiftdir,
                "Offset": abs(float(row["Shift"]/MHz)),
                "Tone": 'Tone' if ctcss else '',
                "rToneFreq": ctcss if ctcss else '88.5',
                "cToneFreq": ctcss if ctcss else '88.5',
                "DtcsCode": '0',
                "DtcsPolarity": 'NN',
                "Mode": 'FM',
                "TStep": '5.00',
                "Skip": '',
                "URCALL": '',
                "RPT1CALL": '',
                "RPT2CALL": '',
                "Comment": row["Location"],
            }
            counter += 1
            outrows.append(out)

        # and write those rows to a CSV file
        with open(csvfile, 'w') as f:
            w = csv.DictWriter(f, outrows[0].keys())
            w.writeheader()
            w.writerows(outrows)


    def write_openstreetfile(self, image, outfile, offset=(8, 8)):
        """ Create a openstreetmap POI XML file
        used to place all repeaters on the map. Literally.
        """
        out = []
        header = "lat\tlon\ttitle\tdescription\ticon\ticonSize\ticonOffset"
        out.append(header)
        for row in self.table:
            try:
                #First try to encode as a city, if that fails do a general query
                try:
                    lat, lon = self._geocoder(row["Location"], 'city')
                except:
                    lat, lon = self._geocoder(row["Location"], 'q')

            except Exception as e:
                log.warn("failed for {}: {}".format(row, e))
                continue

            out.append("{}\t{}\t{}\t{}\t{}\t16,16\t{},{}".format(lat, lon, row["Callsign"],
                                                                       "RX: {RX}, CTCSS: {CT}, Shift: {SH}MHz"
                                                                       .format(RX=row["Frequency"], TX=row["TX_Frequency"], CT=row["CTCSS"], SH=row['Shift']/MHz),
                                                                       image, offset[0], offset[1]))
        #Write the list to the file
        outstr = '\n'.join(out) + '\n'
        with open(outfile, 'w') as f:
            f.write(outstr)


    def _geocoder(self, place, placetype='city'):
        url = "https://nominatim.openstreetmap.org/search?{type}={place}&format=json"
        res = requests.get(url.format(type=placetype, place=place)).text
        loc = json.loads(res)
        lat = loc[0]['lat']
        lon = loc[0]['lon']
        time.sleep(random.randrange(1, 8)/10.0)
        return (lat, lon)

if __name__ == "__main__":
    #log when started
    log.info('Started on {}'.format(datetime.datetime.now()))

    prefix = "repeaters/"
    table_28 = Source.Hamnieuws().getRepeaters(28)
    out_28 = Output(table_28)
    out_28.write_csv(prefix + "csv_28.csv")
    out_28.write_chirp_csv(prefix + "chirp_28.csv", '-')
    out_28.write_openstreetfile("http://serv.pa8q.nl/repeaters/ant_28.png", prefix +"osm_28.xml", (-16, -16))

    table_144 = Source.Hamnieuws().getRepeaters(144)
    out_144 = Output(table_144)
    out_144.write_csv(prefix + "csv_144.csv")
    out_144.write_chirp_csv(prefix + "chirp_144.csv", '-')
    out_144.write_openstreetfile("http://serv.pa8q.nl/repeaters/ant_144.png", prefix +"osm_144.xml", (-8, -8))

    table_430 = Source.Hamnieuws().getRepeaters(430)
    out_430 = Output(table_430)
    out_430.write_csv(prefix + "csv_430.csv")
    out_430.write_chirp_csv(prefix + "chirp_430.csv", '+')
    out_430.write_openstreetfile("http://serv.pa8q.nl/repeaters/ant_430.png", prefix +"osm_430.xml", (0, 0))

    table_1298 = Source.Hamnieuws().getRepeaters(1298)
    out_1298 = Output(table_1298)
    out_1298.write_csv(prefix + "csv_1298.csv")
    out_1298.write_chirp_csv(prefix + "chirp_1298.csv", '-')
    out_1298.write_openstreetfile("http://serv.pa8q.nl/repeaters/ant_1298.png", prefix +"osm_1298.xml", (8, 8))


    log.info('Done on {}'.format(datetime.datetime.now()))
