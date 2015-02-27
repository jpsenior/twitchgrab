#!/usr/bin/python
#The MIT License (MIT)
#
#Copyright (c) 2014 JP Senior (jp.senior@gmail.com)
#
#Permission is hereby granted, free of charge, to any person obtaining a copy
#of this software and associated documentation files (the "Software"), to deal
#in the Software without restriction, including without limitation the rights
#to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#copies of the Software, and to permit persons to whom the Software is
#furnished to do so, subject to the following conditions:
#
#The above copyright notice and this permission notice shall be included in
#all copies or substantial portions of the Software.
#
#THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
#THE SOFTWARE.
#
# Application to capture twitch.tv streams in realtime, rename them based on
# the name of the current game name, and stitch all streams to one large
# file.
#
# requires packages on top of default install:
#  * python-slugify -- translates game name to a valid filesystem name
#  * livestreamer -- CLI application to download Twitch stream sessions
#
# Usage:  Right now, only as a module in python interactive shell during
# development
#
# ./twitchgrab.py streamername
#
# Will constantly run (until it dies) every 1 minute to obtain a username
# and all the stream data therein
# Files will be written to *.ts files
# then moved to webdir/ts/



import requests, json, subprocess, signal, os, re
from threading import Timer,Thread
from slugify import slugify
from datetime import datetime


streamer = 'streamername
oauth = 'Oath key here'
webdir = '/opt/twitchgrab/web'


url = 'http://twitch.tv/%s' % streamer
quality = 'best'
tickinterval = 60
debug = False


blacklist={
  'nonesmania':r'(?i)nonesmania',
  'nocapture':r'(?i)nocapture',
  'Streamer disabled camera':r'(?i)nocam',
}

#Do not edit anything beyond this line!

#Make thisobject global so it's easy to debug with tick.stop()
tick = None

#Prints diagnostics information
def debugprint(text):
  if debug == True:
    print("Debug: %s", text)

#StreamThread is the master object that drives the subprocesses used to thread
#and capture livestreamer output.  StreamThread intelligently renames files,
#and rolls over intelligently when the game either stops playing or is changed
#to another game.
#Usage: StreamThread('sartandragonbane')
class StreamThread(Thread):
  def __init__(self, streamer):
    self.streamer = streamer
    self.game = None
    self.thread = None
    self.fname = 'unknown'
    self.quality = 'best'
    self.url = 'http://twitch.tv/%s' % self.streamer
    self.runstate = False
    self.finished = False
    Thread.__init__(self)

  #Builds a filename based on the currently streaming game name from Twitch.
  def getfname(self):
    #TODO:  Check existing filesystem for existing file names.
    dt = datetime.now().strftime("%Y-%m-%d_%H-%M")
    fname = '%s-%s.ts' % (slugify('%s %s' % (self.streamer, self.newgame())), dt)
    debugprint("Filename created: %s" % (fname))
    self.fname = fname
    return self.fname

  #Grab the most up to date game name from Twitch.
  def newgame(self):
      #Grab JSON from twitch API
      #TODO: OAUTH session so we don't get timed out.
      r = requests.get('https://api.twitch.tv/kraken/streams/%s' % ( self.streamer ), headers={"Authorization": "OAuth %s" % oauth})
      data = r.json()
      #Only active streamers will have the stream data we need.
      try:
        status = data["stream"]["channel"]["status"]
        for r in blacklist:
          result = re.search(blacklist[r], status)
          if result:
            print "Stream blacklisted: %s -> %s" % ( blacklist[r],result.group(0))
            return None
      except:
        print "key error"
        pass
      try:
        if data["stream"]:
          if data["stream"]["game"]:
            game = data["stream"]["game"]
            return game
          elif data["stream"]["channel"]["status"]:
            game = data["stream"]["channel"]["status"]
            return game
        #Abort!
        print "Warning: %s is not streaming right now" % ( streamer )
        return None
      except KeyError:
        print "Warning: %s is not streaming right now" % ( streamer )
        return None

  #This is intended to be used every 60 seconds -- keep calling it safely!
  def start(self):
    newgame = self.newgame()
    runstate = self.running()
    #if the game has changed, and the streamer is still playing a new game:
    print("Existing game: %s New game: %s" % (self.game, newgame))

    #If there is supposed to be a game running and there is not, start the capture.
    if newgame != None and runstate == False:
      self.game = newgame
      self.capture()
    #If the game changes to a valid game, stop the current stream and start again.
    elif newgame != self.game and not newgame == None:
      print "Game '%s' changed from old '%s', starting a new stream!" % (self.game, newgame)
      #If the stream is running, stop it.
      if runstate == True:
        print "Stopping existing stream"
        self.stop()
      self.game = newgame
      self.capture()
    else:
      debugprint("Same game.")

  #Checks if there is a valid process running for this thread object
  def running(self):
    try:
      #We have to poll first to get the returncode.
      #process is a zombie until we do.
      poll = self.thread.poll()
      poll = self.thread.returncode
      #If the process is running poll = None
      if poll == None:
        return True
        debugprint("THREAD: Thread is still running, poll none")
      else:
        if self.runstate == True:
          self.stop()
        debugprint("ERROR: Thread may be a spoooky zombie")
        #This is probably a defunct process so let's just kill it here.
        return False
    #A thread that is not running has no poll object.t.
    except AttributeError:
      debugprint( "Thread was not ever started")
      return False

  #When the stream finishes, let's join all of the chunks (if necessary).
  def finish(self):
    try:
      if self.finished == False and self.thread.returncode != 1:
        print "Stitch up videos with FFMPEG -- assume we are done!"
        print "Intelligently join files together based on filename"
        print "Once stitch is done, move completed stream to master folder"
        print "File moved to %s%s%s" % (webdir, '/ts/', self.fname)
        self.finished = True
        os.rename(self.fname, webdir + '/ts/' + self.fname)
      else:
        debugprint("FINISHED: Already done!")
    except:
      pass


  #Start the livestream based on data above.
  def capture(self):
    if not self.running():
      # each iteration of filename should increase by one, to prevent overwriting previous streams
      # in case the stream breaks and drops offline for a longer time
      # than player-continuous-http can deal with

      #this process runs for a while, outputting stream progress until it is stopped (signal)
      #stdout continually looks like [download][..ndragonbane-m-c-kids.ts] Written 9.6 MB (1m6s @ 149.1 KB/s
      self.runstate = True
      self.finished = False
      self.fname = self.getfname()
      print "Beginning stream capture ", self.fname
      self.thread = subprocess.Popen(['/usr/bin/livestreamer', "-f", "-player-continuous-http", "-o", self.fname, self.url, self.quality ])

  #Stop the currently running stream and run any finishing cleanup jobs if needed.
  def stop(self):
    print "Stopping this stream."
    #Send a nice graceful interrupt to the sub process
    try:
      self.runstate = False
      self.thread.terminate()
    #It might take a few seconds to clean up.
      self.thread.wait()
    #If it ain't running who cares
    except OSError:
      pass
    self.finish()
    #Good place to add IRC announcements if necessary.

#The stream timer is a wrapper object used to regularly run various stream commands,
#found elsewhere in StreamThread
class StreamTimer(object):
  def __init__(self,interval = 60.0):
    self.interval = interval
    self.stoptimer = False
    self.timer = None
    self.streamthread = StreamThread(streamer)

  #Tick is the looping process that runs every 'interval' seconds.
  def tick(self):
    debugprint("Tick")
    if self.stoptimer == True:
      print "All done!"
    else:
      #Start another timer object.
      self.timer = Timer(self.interval, self.tick).start()
      self.action()

  #Seperate action from start so we can run immediately without waiting
  def action(self):
    self.streamthread.start()

  #Start the tick timer.
  def start(self):
    self.stoptimer = False
    self.tick()

  def stop(self):
    print "Ticker loop stopping!!"
    self.stoptimer = True
    self.streamthread.stop()

#This code should only run if we are using this as a command line.
def main():
  #TODO:
  #worker process threads here to capture keyboardinterrupt
  print "Beginning to watch %s for new videos on Twitch.tv" % streamer
  #Build the ticker object.
  tick = StreamTimer(interval=tickinterval)
  tick.start()

#Python automatically executes __main__ when running from cli.
if __name__ == "__main__":
    main()
