import uuid
import threading
import time
import queue
import os
import zipfile
import shutil

from flask import Flask
from flask import render_template
from flask import request
from flask import json, jsonify

from MAVProxy.modules.mavproxy_map import srtm

from terrain_gen import makeTerrain

# The output folder for all zipped terrain requests
app = Flask(__name__,static_url_path='/terrain', static_folder='outputTer',)

def clamp(n, smallest, largest):
    return max(smallest, min(n, largest))

class TerGenThread(threading.Thread):
    # This is the terrain generator. It will check the queue 
    # for new requests.
    def __init__(self):
        threading.Thread.__init__(self)
        self.event = threading.Event()
        # SRTM downloader. Single instance passed to terrain generator
        self.downloader = srtm.SRTMDownloader(debug=False, cachedir='./srtmcache')
        self.downloader.loadFileList()
        self.terStats = {}
        self.terQ = queue.Queue()

    def addStatus(self, uuidkey, value):
        self.terStats[uuidkey] = value

    def run(self):
        print("Starting Terrain Generator")
        while not self.event.is_set():
            time.sleep(0.01)
            if not self.terQ.empty():
                (radius, lat, lon, spacing, uuidkey, outfolder) = self.terQ.get()
                print("Starting request: " + str(uuidkey))
                self.terStats[uuidkey] = "Processing"
                # generate terrain
                makeTerrain(self.downloader, radius, lat, lon, spacing, uuidkey, outfolder)
                
                self.terStats[uuidkey] = "Compressing"
                #compress into single file for user
                folderthis = os.path.join(os.getcwd(), outfolder + "-tmp", uuidkey)
                zipthis = os.path.join(os.getcwd(), outfolder, uuidkey + '.zip')
                terrain_zip = zipfile.ZipFile(zipthis, 'w')
                 
                print("At Compress ")
                #numpercent  = numpercent * 1.1
                for folder, subfolders, files in os.walk(folderthis):
                    for file in files:
                        terrain_zip.write(os.path.join(folder, file), file, compress_type = zipfile.ZIP_DEFLATED)
                 
                terrain_zip.close()

                #remove old folder
                try:
                    shutil.rmtree(folderthis)
                except OSError as e:
                    print("Error: %s : %s" % (folderthis, e.strerror))

                print("At Done")

                del self.terStats[uuidkey]

        print("Exiting Terrain Generator")

# Terrain generator checker
x = TerGenThread()
x.start()

def queueStatus():
    return len(x.terStats)

def wholeStat():
    return str(x.terStats)

def shutdown():
    x.event.set()
    x.join()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods = ['GET', 'POST'])
def generate():
    if request.method == 'POST':
        # parse and sanitise the input
        try:
            # request.form['username']
            lat = float(request.form['lat'])
            lon = float(request.form['long'])
            radius = int(request.form['radius'])
            assert lat < 90
            assert lon < 180
            assert lat > -90
            assert lon > -180
            radius = clamp(radius, 1, 400)
        except:
            print("Bad data")
            return render_template('generate.html', error = "Error with input")

        # UUID for this terrain generation
        uuidkey = str(uuid.uuid1())

        # Add this job to the processing queue
        x.terQ.put((radius, lat, lon, 100, uuidkey, 'outputTer'))
        #x.terStats[uuidkey] = "In Queue, pos={0}".format(terQ.qsize())
        x.addStatus(uuidkey, "In Queue, pos={0}".format(x.terQ.qsize()))

        return render_template('generate.html', urlkey="/terrain/" + uuidkey + ".zip", waittime=x.terQ.qsize()+1, uuidkey=uuidkey)
    else:
        print("Bad get")
        return render_template('generate.html', error = "Need to use POST, not GET")

@app.route('/status/<uuid:uuidkey>')
def status(uuidkey):
    if not uuidkey:
        return jsonify(status = 'Error: incorrect UUID')
    elif str(uuidkey) in x.terStats:
        return jsonify(status = 'success', data = str(x.terStats[str(uuidkey)]))
    elif os.path.exists(os.path.join('.', 'outputTer', str(uuidkey) + ".zip")):
        return jsonify(status = 'success', data = "ready")
    else:
        return jsonify(status = 'Error: bad UUID ' + str(os.path.join('.', 'outputTer', str(uuidkey) + ".zip")))
