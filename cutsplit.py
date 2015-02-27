#!/usr/bin/python
#Copyright (c) 2014 Sacharun (scripts@sacharun.com)
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
#
# This app takes a video file, and stitches together cuts defined in an EDL file
# Intended mainly for users of sites like twitch.tv to remotely edit and transfer videos to youtube.
#
# requires packages on top of default install:
#  * ffmpeg -- compiled with lib_x264 if re-encoding (re-encoding is not currently implemented)
#
# recommended other packages:
# twitchgrabber.py - automatically downloads a stream as it is broadcast (avoids muting)
# voddl.py - for downloading vods (nb. muted vods aren't currently handled well)
#
# Usage:

def usage():
        print "\n Usage: cutsplit.py [-k int] -e edlfile -i infile -o outfile [-t tempdir] OR cutsplit.py [-k int] -i infile -o outbasename -s splitfile \n\n"
        print "EDL must have 2 timestamps per line From and To in format HH:MM:SS:FF (FF=frame number) \n"
        print "Splitfile must have one timestamp per line in format HH:MM:SS.mmm \n"
        print "-k - if the video has set interval between keyframes, you can set that here and cuts will be done on the keyframe (default x264 is one every 250 frames, OBS recommends 1 every 2 sec)"

#cutsplit.py
#interesting functions :
# cut(edlfile, infile, outfile, tempdir="./") - takes an edl file and renders out
# split(splitfile, infile, outbasename) - takes a file of split points and cuts up a video
# joinsegments(segmentlist, outfile) - takes a list of filenames and joins them into one video

#parses .edl to look for lines with at least 2 timestamps, then grabs the first 2 as $start & $end
#example line: 001  AX       AA/V  C        00:00:00:00 00:00:10:03 00:10:00:00 00:10:10:03
#will make a segment from the start of a file to 10sec and 3 frames & will ignore the other timestamps

#todo - get rid of shell=True for better security
#         - remove -bsf:a aac_adtstoasc (if working from mp4 input)
#         - get fps from infile
#         - auto detect keyframe for better cutting
#         - option to re-encode for youtube
#         - youtube upload option, with prompt for split times if video over 11 hrs
#         - handle muted vods gracefully (insert a silent audio track)

import re #for regex matching
import subprocess #for executing shell commands
import os #file rename & delete

import getopt, sys #commandline arguements

fps = 60 #todo: get actual fps from file
__k__ = None #if the video has set interval keyframes, you can set that here and cuts will be done on the keyframe (also can use the -k option)

#opens the edl, finds first 2 timestamps on each line, and returns them in a list
def iterateEdl(edlFile):
        timestampList = []
        r = re.compile("[0-9]{2,}:[0-9]{2}:[0-9]{2}:[0-9]{2,}")
        with open(edlFile) as edl:
                for line in edl:
                        #print line
                        mo = r.findall (line)
                        if len(mo) < 2: continue
                        #print "match in :" + line
                        start = mo[0]
                        stop = mo[1]
                        print "timestamp added to list - " + start + " to " + stop
                        timestampList.append ( {'start': start, 'stop': stop} )

        return timestampList

#optimise a cut point to land on a keyframe, given a keyframe every __k__ seconds
def optimise(startStamp):
        segments = startStamp.split (':')
        segments[2] = float (segments[2])

        #todo: logic to snap to __k__ interval goes here
        diff = segments[2] % __k__
        if __k__ / 2 < diff:
                diff = __k__ - diff
                segments[2] = segments[2] + diff
        else:
                segments[2] = segments[2] - diff

        segments[2] = round(segments[2],0)
        segments[2] = segments[2] - 0.1
        #segments[2] = str (segments[2])
        startStamp = int (segments[0]) * 3600 + int (segments[1]) * 60 + segments[2]
        return str(startStamp)

#converts STMPE time stamps (used in edl files) and converts them to std time (used in ffmpeg)
def STMPEtoSec (timeStamp, fps):
                #split timestamp
        tlist = timeStamp.split(":")
                #convert 4th segement to ms
        tlist[3] = str(int(1000.0/fps * int(tlist[3]))).zfill(3)
                #rejoin & return timestamp
        outStamp = tlist[0] + ":" + tlist[1] + ":" + tlist[2] + "." + tlist[3]
        return outStamp


def segment(infile, outfile, start, stop):
        ffmpegcommand = "ffmpeg -i "+ infile +" -acodec copy -vcodec copy -bsf:a aac_adtstoasc -ss "+ start +" -to "+ stop +" "+ outfile
        print "Calling: " + ffmpegcommand
        subprocess.call(ffmpegcommand, shell=True)



def joinsegments(segmentlist, outfile):

        segmentfile = outfile + ".segmentlist"
        with open(segmentfile, 'w') as f:
                for file in segmentlist:
                        f.write('file \''+ file + '\'\n')

        ffmpegCommand = "ffmpeg -f concat -i " + segmentfile + " -c copy -bsf:a aac_adtstoasc -movflags faststart "+ outfile
        print "Calling: " + ffmpegCommand
        subprocess.call(ffmpegCommand, shell=True)
        os.remove(segmentfile)

from decimal import Decimal

def get_video_length(path):
        process = subprocess.Popen(['/usr/local/bin/ffmpeg', '-i', path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        stdout, stderr = process.communicate()
        matches = re.search(r"Duration:\s{1}(?P\d+?):(?P\d+?):(?P\d+\.\d+?),", stdout, re.DOTALL).groupdict()

        hours = Decimal(matches['hours'])
        minutes = Decimal(matches['minutes'])
        seconds = Decimal(matches['seconds'])

        total = 0
        total += 60 * 60 * hours
        total += 60 * minutes
        total += seconds
        return total

def deletesegments(segmentlist):
        for file in segmentlist:
                os.remove(file)

#call arguements -edl edlfile -i infile -o outfile [-tmp tempdir]
def cut(edlfile, infile, outfile, tempdir="./"):

        segmentList = []
        timestampList = iterateEdl(edlfile)
        segmentCount=1
        for timeStamp in timestampList:
                startStamp = STMPEtoSec(timeStamp['start'], fps)
                stopStamp = STMPEtoSec(timeStamp['stop'], fps)
                if __k__: startStamp = optimise(startStamp)
                segmentList.append (tempdir+outfile+"_tmp_"+ str(segmentCount) +".mp4")
                segment(infile, segmentList[len(segmentList)-1], startStamp, stopStamp)
                segmentCount += 1

        if segmentCount > 2:
                joinsegments(segmentList, outfile)
                deletesegments(segmentList)
        else:
                os.rename(segmentList[0], outfile)
#       if get_video_length(outfile) > 39600: #39600 seconds is 11 hours
#               print "Warning! video is longer than 11 hours!"

def split(splitfile, infile, outbasename):
        cutFrom = '00:00:00'
        splitcount=1
        with open(splitfile) as splits:
                for line in splits:
                        cutTo = line.rstrip()
                        if __k__: cutTo = optimise(cutTo)
                        subprocess.call("ffmpeg -i "+ infile +" -acodec copy -vcodec copy -bsf:a aac_adtstoasc -ss "+ cutFrom +" -to "+ cutTo + " " + outbasename + str(splitcount) +".mp4", shell=True)
                        cutFrom = cutTo
                        splitcount +=1
        subprocess.call("ffmpeg -i "+ infile +" -acodec copy -vcodec copy -bsf:a aac_adtstoasc -ss "+ cutFrom +" " + outbasename + str(splitcount) +".mp4", shell=True)


#call arguements -e edlfile -i infile -o outfile [-t tempdir]
def main(argv):
        try:
                opts, args = getopt.getopt(sys.argv[1:], "he:i:o:t:s:k:")
        except getopt.GetoptError, err:
                print str(err)
                usage()
                sys.exit(2)

        tempdir = './'
        global __k__
        for opt, arg in opts:
                        if opt == "-k":
                                __k__ = float(arg)
                        if opt == "-h":
                                usage()
                        if opt == "-e":
                                edlfile = arg
                        if opt == '-i':
                                infile = arg
                        if opt == '-o':
                                outfile = arg
                        if opt == '-t':
                                tempdir = arg
                        if opt == '-s':
                                splitfile = arg
                                split(splitfile, infile, outfile)
                                sys.exit()
#       try:
        cut(edlfile, infile, outfile, tempdir)
#       except:
#               usage()
#               sys.exit(2)




if __name__ == "__main__":
    main(sys.argv[1:])
