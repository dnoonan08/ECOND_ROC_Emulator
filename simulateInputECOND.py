import argparse
import pandas as pd
import numpy as np
import os
import random
import shutil
import warnings

import glob

###############################################
# ROC Emulation response 
###############################################
#
# arguments:
# - N: number of fast commands
# - delay: number of BXs that takes the ROC to respond to a L1A
# - l1a: send this number of L1As
# - l1a-freq: send 1 L1As in l1a-freq BXs
#
###############################################

# global parameters
ORBITLAST = 3564
ORBITBCR = ORBITLAST - 50

# commands
CMD_IDLE = "FASTCMD_IDLE"
CMD_L1A = "FASTCMD_L1A"
CMD_BCR = "FASTCMD_BCR"
CMD_BCROCR = "FASTCMD_BCR_OCR"
CMD_ECR = "FASTCMD_ECR"
CMD_EBR = "FASTCMD_EBR"
CMD_ALLONE = "FASTCMD_ALLONE"

# daq words format
# 41 words (32 bits each) - 40 BX + IDLE
# each word is separated by _ and takes 1 BX to read (32 bit word: 1.8 gHz: 32* 40MHz)
# HDR (header) + CM (common mode) + CH_i i:0-37 (36 channels + calibration) + CRC (checksum) + IDLE
# HDR: 0101 + 12bit Bx# + 6bit Event# + 3bit Orbit# + 1bit H1status + 1bit H2status + 1bitH3status + 0101
# CM: 10 + 10bit + 10bitADC(CM0) + 10bitADC(CM1)
# IDLE: continuosly sent out when no L1A
DATAWORDS = 'HDR_'+'CM_'
for i in range(37): DATAWORDS += 'CH%i_'%i
DATAWORDS += 'CRC_' + 'IDLE'
NWORDS = len(DATAWORDS.split('_'))

# words
IDLEWORD_BC0_hex = 0x9ccccccc
IDLEWORD_hex = 0xaccccccc
IDLEWORD_BC0 = '9CCCCCCC'
IDLEWORD = 'ACCCCCCC'
ONEWORD_hex = 0xffffffff

def produceL1AFastCommands(args):
    sequences = args.sequence.split(',')
    nL1As = args.nL1A.split(',')
    L1A_freqs = args.L1A_freq.split(',')
    L1ABXs = []
    iL1A = 0
    L1Aname = ''
    for i,s in enumerate(sequences):
        nL1A = int(nL1As[i]) if (len(nL1As)>i and nL1As[i]!='') else -1
        L1A_freq = int(L1A_freqs[i]) if (len(L1A_freqs)>i and L1A_freqs[i]!='') else 53 # default freq
        maxL1A = nL1A+1 if nL1A>-1 else args.N
        bxs=[]
        if s=='fixed':
            bxs = np.array([(i+1)*L1A_freq for i in range(iL1A,iL1A+maxL1A) if (i+1)*L1A_freq<args.N])
            print(bxs,iL1A,iL1A+maxL1A,(i+1)*L1A_freq,[(i+1)*L1A_freq for i in range(iL1A,iL1A+maxL1A)])
            #0 3 100
        elif s=='random':
            np.random.seed(6)
            bxs = np.random.choice(np.arange(iL1A,iL1A+maxL1A), np.random.poisson(args.N*1./L1A_freq), replace=False)
        else:
            print('no such sequence')
        if len(bxs)>0:
            L1ABXs.extend(bxs)
            L1Aname += str(len(bxs)) + 'L1As-' + s + 'freq' + str(L1A_freq)
            iL1A = maxL1A
    print('L1A BXs ',np.array(L1ABXs))
    return np.array(L1ABXs),L1Aname

def bxCounter(i,fc):
    bxc = i%ORBITLAST
    if fc==CMD_BCR or fc==CMD_BCROCR: bxc = ORBITBCR
    return bxc

def orbitCounter(i,fc):
    orbitc = int(i/ORBITLAST)
    if fc==CMD_BCROCR: orbitc = 0
    return orbitc

def produceFastCommands(args):
    N = args.N
    
    fastCommands = np.array([CMD_IDLE] * N, dtype='object')

    if args.bcr:
        # assume bcr sent at BX=3513
        bcrBXs = [i for i in range(len(fastCommands)) if i%ORBITLAST==ORBITBCR]
        # extra bcrs
        if args.extra_bcr:
            bcrBXs += [2000]
        # missing bcrs
        if args.missing_bcr:
            bcrBXs.pop(0)        
        fastCommands[bcrBXs] = CMD_BCR

    if args.bocr:
        # assume ocr sent at BX=3513
        ocrBXs = [i for i in range(len(fastCommands)) if i%ORBITLAST==ORBITBCR]
        fastCommands[ocrBXs] = CMD_BCROCR

    if args.ecr and args.ecrBX!='':
        # assume ecr sent at unique globalBXs
        ecrBXs = [int(ecr) for ecr in args.ecrBX.split(',')]
        print('send ecr ',ecrBXs)
        fastCommands[ecrBXs] = CMD_ECR
        
    if args.ebr and args.ebrBX!='':
        ebrBXs = [int(ebr) for ebr in args.ebrBX.split(',')]
        print('send ebr ',ebrBXs)
        fastCommands[ebrBXs] = CMD_EBR
        
    # add L1As
    L1ABXs,L1Aname = produceL1AFastCommands(args)    
    fastCommands[L1ABXs] = CMD_L1A

    # command - orbit - bx - globalBx
    fastCommandsL = [{'fc':fc, 'orbit':orbitCounter(i,fc), 'BX':bxCounter(i,fc), 'globalBX':i}  for i,fc in enumerate(fastCommands)]
    return fastCommandsL,L1Aname

def produceEportRX_input(args):
    
    # produce idle fast commands w. other fast commands
    fastCommands, L1Aname = produceFastCommands(args)
    
    # output data
    channels = ['Hard reset', 'Soft reset']
    for i in range(0,12):
        channels.append('Aligner Ch%i (32 bit)'%i)
    channels.append('Fast Command (8 bit)')

    # start
    ch2start = dict.fromkeys(channels)
    ch2start['Hard reset'] = [1]
    ch2start['Soft reset'] = [1]
    for i in range(0,12): ch2start['Aligner Ch%i (32 bit)'%i] = [IDLEWORD]
    ch2start['Fast Command (8 bit)'] = [CMD_IDLE]

    # reset
    ch2reset = dict.fromkeys(channels)
    ch2reset['Hard reset'] = [0] * 3
    ch2reset['Soft reset'] = [1] * 3
    for i in range(0,12): ch2reset['Aligner Ch%i (32 bit)'%i] = [IDLEWORD] * 3
    ch2reset['Fast Command (8 bit)'] = [CMD_IDLE] * 3

    # finish
    ch2finish = dict.fromkeys(channels)
    ch2finish['Hard reset'] = [1]
    ch2finish['Soft reset'] = [1]
    for i in range(0,12): ch2finish['Aligner Ch%i (32 bit)'%i] = ['{0:08X}'.format(int('{0:032b}'.format(ONEWORD_hex),base=2))]
    ch2finish['Fast Command (8 bit)'] = [CMD_ALLONE] 
    
    # dataDAQ
    ch2data = dict.fromkeys(channels)
    ch2data['Hard reset'] = []
    ch2data['Soft reset'] = []
    ch2data['Fast Command (8 bit)'] = []
    rocData = []

    # buffers
    # eventBuffer:
    #  [ [], [], .. times number of events in buffer]
    #  should contain the index of the event number to read from the daqBuffer
    #  since we are producing random data (instead of simulation) we just fill this buffer with empty lists as a placehold
    #
    # delayBuffer:
    #  [BX for the event w. L1A accept, number of BX that will take to read this event]
    #  we always read the first element in the delayBuffer list
    #  if it is empty we send idles, if not we read words from the event in the daqBuffer 
    #  once we have stopped reading those words we remove the first element of the delayBuffer
    #  and this converts the next event to read into the first element
    delayBuffer = []
    eventBuffer = []
    iBuffer=0;iEvent=0;

    # loop over fast commands
    nfc = args.N
    i = 0
    while i < nfc:
        command_ = fastCommands[i]['fc'] if len(fastCommands)>i else CMD_IDLE
        bx_ = fastCommands[i]['BX'] if len(fastCommands)>i else bxCounter(i,command_)

        # fill in other columns
        ch2data['Hard reset'].append(1)
        ch2data['Soft reset'].append(1)
        ch2data['Fast Command (8 bit)'].append(command_)
        
        # if L1A then pull event out of daq buffer to event buffer
        if command_ == CMD_L1A:
            # set delay
            if len(eventBuffer)==0:
                # if buffer is empty: get evt in delay time (e.g. 7BX)
                delay=args.delay
                start=i+delay
            else:
                # if buffer is not empty:
                #    if the length(buffer) < delay_time: get evt in delay time (e.g. 7BX)
                #    else: get evt in (delay time - (words to finish))
                nWordsToFinish = NWORDS-len(eventBuffer[-1])
                if nWordsToFinish >= args.delay:
                    delay=0
                else:
                    delay=args.delay-nWordsToFinish
                start=delayBuffer[-1]['start']+NWORDS+delay
                
            print('L1A at BX: ',i,' Events in buffer: ',len(eventBuffer),' Latency delay: ',delay,' Start reading this evt at: ',start,' Finish at ',start+NWORDS-1)

            # calculate how long it will take to read:
            # if empty: range(i+delay, i+delay+nwords)
            # whentheotehrwillfinish = i+(nWords-len(eventBuffer[0]))
            # not: range(whentheotehrwillfinish+delay,whentheotehrwillfinish+delay+nwords)
            
            # append event to eventBuffer - just so that we know an event is coming
            # for now is an empty list - but it should be the index of the event to pull from the daqBuffer
            eventBuffer.append([])
            # append current BX (i) and # of BXs that will take to read this event (i + delay + nWords)
            delayBuffer.append({'globalBX':i,'start':start,'finish':start+NWORDS-1})
            print('events in buffer',eventBuffer)
            #print('evtBuff ',eventBuffer, 'delayBuffer',delayBuffer)

        # if ECR, then reset the event counter 
        if command_ == CMD_ECR:
            iEvent = 0

        # if EBR, then reset the event buffer
        if command_ == CMD_EBR:
            print('send ebr ',i,eventBuffer,' ibuffer ',iBuffer)
            if( (len(eventBuffer)==1 and iBuffer==0) or len(eventBuffer)>1):
                eventBuffer = [] # not clear just get the first out?
                delayBuffer = []
                iEvent = 0
            print(eventBuffer)

        dataType = 'IDLE' # data type by default
        idleWord = IDLEWORD_BC0 if bx_==0 else IDLEWORD
        idleWord_hex = IDLEWORD_BC0_hex if bx_==0 else IDLEWORD_hex
            
        # replace nfc with the last event to read
        if len(delayBuffer)>0 and delayBuffer[-1]['finish']>=args.N:
            nfc = delayBuffer[-1]['finish']+1
            
        # read event buffer - read one word in one BX
        if len(eventBuffer)>0:
            #print('reading evt buffer')
            delayBx = delayBuffer[0]['globalBX']
            bx = fastCommands[delayBx]['BX'] 
            orbit = fastCommands[delayBx]['orbit']
            #print('reading ',i,' iBuff ',iBuffer ,' NWORDS ',NWORDS,' delayBuff ',delayBuffer[0])
            if i>=delayBuffer[0]['start'] and i<=delayBuffer[0]['finish'] and iBuffer<NWORDS:
                print(i,'reading',delayBx,' len ',len(eventBuffer[0]))
                # here you would pick the data from that event..
                # let's set to random and zeros:
                data = DATAWORDS.split('_')[iBuffer]
                dataType = data
                if data=='HDR':
                    data ='0101'
                    print('HDR ',iEvent,delayBx)
                    data += '{0:012b}'.format(bx & 0b111111111111) # bx
                    data += '{0:06b}'.format(iEvent & 0b111111) # event
                    data += '{0:03b}'.format(orbit & 0b111) # orbit
                    data += '{0:01b}'.format(random.getrandbits(1)) #H1
                    data += '{0:01b}'.format(random.getrandbits(1)) #H2
                    data += '{0:01b}'.format(random.getrandbits(1)) #H3
                    data += '0101'
                elif data=='CM':
                    data = '10'
                    data += '{0:010b}'.format(0)
                    data += '{0:010b}'.format(random.getrandbits(10)) # ADC-CM0
                    data += '{0:010b}'.format(random.getrandbits(10)) # ADC-CM1
                elif data=='IDLE':
                    data = '{0:032b}'.format(idleWord_hex)
                else:
                    # else a zero 32-bit word
                    data = '{0:032b}'.format(0)

                # convert to hex
                data = '{0:08X}'.format(int(data,base=2))
                                
                eventBuffer[0].append( data)
                rocData.append(data)
                iBuffer+=1
                if len(eventBuffer[0])==NWORDS:
                    iEvent+=1
                    eventBuffer.pop(0)
                    delayBuffer.pop(0)
                    iBuffer=0
                    print('finish reading event ',iEvent,' at i ',i,' words in evtBuffer ',eventBuffer,' delay buffer ',delayBuffer)
                else:
                    if i==args.N-1:
                        print('last ',i,'reading ',iBuffer)
            else:
                rocData.append(idleWord)
        else:
            rocData.append(idleWord)

        # increment counter
        i+=1
                    
    # append channel data
    for i in range(0,12):
        ch2data['Aligner Ch%i (32 bit)'%i] = rocData

    # creating dataframes
    df_start = pd.DataFrame.from_dict(ch2start)
    df_reset = pd.DataFrame.from_dict(ch2reset)
    df_data = pd.DataFrame.from_dict(ch2data)
    df_finish = pd.DataFrame.from_dict(ch2finish)

    # write csv
    fname_tmp = "ROC_DAQ_%ifc_"%args.N

    if L1Aname!='':
        fname_tmp += L1Aname
    if args.bcr:
        fname_tmp += "_wbcr"
        if args.missing_bcr:
            fname_tmp += "_missingbcr"
        if args.extra_bcr:
            fname_tmp += "_extrabcr"
    if args.bocr:
        fname_tmp += "_wbocr"
    if args.ecr and args.ecrBX!='':
        fname_tmp += "_wecrBX" + args.ecrBX.replace(',','-')
    if args.ebr and args.ebrBX!='':
        fname_tmp += "_webrBX" + args.ebrBX.replace(',','-')
        
    f = open('rocData/%s.csv'%fname_tmp, 'w')
    desc = "# Provides a simple reset and then %i fast commands"%nfc
    if L1Aname!='':
        desc+=" with %i event packets (with %i BXs of delay)\n"%(iEvent,args.delay)
        desc += "# The data idle word will contain the special 0x9 header for BC0\n"
    else:
        desc+="\n"
    f.write(desc)
    f.write("# "+",".join(channels)+"\n")
    f.write("# start\n")
    df_start.to_csv(f, index=False, header=False)
    f.write("# reset\n")
    df_reset.to_csv(f, index=False, header=False)
    f.write("# %i fast commands \n"%args.N)
    df_data.to_csv(f, index=False, header=False)
    f.write("# finish\n")
    df_finish.to_csv(f, index=False, header=False)
    f.close()
    
if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-N', type=int, default = 10000, dest="N", help="Number of BX to use (default: 10000)")
    parser.add_argument('--bcr', action='store_true', default= False, dest="bcr", help="Send BCRs")
    parser.add_argument('--missing-bcr', action='store_true', default= False, dest="missing_bcr", help="Send BCRs")
    parser.add_argument('--extra-bcr', action='store_true', default= False, dest="extra_bcr", help="Send BCRs")
    parser.add_argument('--bocr', action='store_true', default= False, dest="bocr", help="Send BCR and OCR")
    parser.add_argument('--ecr', action='store_true', default= False, dest="ecr", help="Send ECRs")
    parser.add_argument('--ecrBX', type=str, default='', dest="ecrBX", help="Send ECRs in these global BXs")
    parser.add_argument('--ebr', action='store_true', default= False, dest="ebr", help="Send EBRs")
    parser.add_argument('--ebrBX', type=str, default='', dest="ebrBX", help="Send EBRs in these global BXs")
    
    parser.add_argument('--delay', type=int, default = 7,dest="delay", help="ROC delay to respond to L1A (in BXs)")

    parser.add_argument('--sequence', type=str, default='', dest="sequence", help="Sequence of L1A patterns to send (separated by ,)")
    parser.add_argument('--nL1A', type=str, default='', dest="nL1A", help="Length of L1A patterns sent")
    parser.add_argument('--L1A_freq', type=str, default='', dest="L1A_freq", help="Send L1As with a frequency of 1 in L1A_freq")
     
    args = parser.parse_args()

    produceEportRX_input(args)
