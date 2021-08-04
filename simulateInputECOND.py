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
#
###############################################

# global parameters
ORBITLAST = 3564
ORBITBCR = ORBITLAST - 50

# fast commands
CMD_IDLE = "FASTCMD_IDLE"
CMD_L1A = "FASTCMD_L1A"
CMD_BCR = "FASTCMD_BCR"
CMD_BCROCR = "FASTCMD_BCR_OCR"
CMD_ECR = "FASTCMD_ECR"
CMD_EBR = "FASTCMD_EBR"
CMD_ALLONE = "FASTCMD_ALLONE"

"""
DAQ words: 41 words (32 bits each)
  each word string is separated by _ and takes 1 BX to read (32 bit word: 1.8 gHz: 32* 40MHz)
  nBXs: 40BX  + IDLE_WORD = 41 BX
  HDR (header) + CM (common mode) + CH_i i:0-37 (36 channels + calibration) + CRC (checksum) + IDLE
  HDR: 0101 + 12bit Bx# + 6bit Event# + 3bit Orbit# + 1bit H1status + 1bit H2status + 1bitH3status + 0101
  CM: 10 + 10bit + 10bitADC(CM0) + 10bitADC(CM1)
  IDLE: continuosly sent out when no L1A
"""
DATAWORDS = 'HDR_'+'CM_'
for i in range(37): DATAWORDS += 'CH%i_'%i
DATAWORDS += 'CRC_' + 'IDLE'
NWORDS = len(DATAWORDS.split('_'))
NELINKS = 12

# HEX pre-defined words
IDLEWORD_HEX = 0xaccccccc
IDLEWORD_BC0 = '9CCCCCCC'
IDLEWORD = 'ACCCCCCC'
ONEWORD_HEX = 0xffffffff

def generate_L1a_fast_commands(args):
    sequences = args.sequence.split(',')
    L1a_nums = args.nL1a.split(',')
    L1a_freqs = args.L1a_freq.split(',')
    L1a_bxs = []
    L1a_counter = 0
    L1a_name = ''
    for i,sequence in enumerate(sequences):
        num = int(L1a_nums[i]) if (len(L1a_nums)>i and L1a_nums[i]!='') else -1
        freq = int(L1a_freqs[i]) if (len(L1a_freqs)>i and L1a_freqs[i]!='') else 53 # default freq
        maxn = num if num>-1 else args.N
        
        bxs=[]
        if sequence=='fixed':
            bxs = np.array([(j+1)*freq for j in range(L1a_counter,L1a_counter+maxn) if (j+1)*freq<args.N])
            # print('fixed ',bxs,L1a_counter,L1a_counter+maxn,[(j+1)*freq for j in range(L1a_counter,L1a_counter+maxn)])
            #0 3 100
        elif sequence=='random':
            np.random.seed(6)
            bxs = np.random.choice(np.arange(L1a_counter,L1a_counter+maxn), np.random.poisson(maxn*1./freq), replace=False)
        else:
            print('no such sequence')
            
        if len(bxs)>0:
            L1a_bxs.extend(bxs)
            L1a_name += str(len(bxs)) + 'L1As-' + sequence + 'freq' + str(freq)
            L1a_counter = maxn
            
    print('L1a bxs ',np.array(L1a_bxs))
    
    return np.array(L1a_bxs),L1a_name

def count_bx(i,fast_command):
    bx_counter = i%ORBITLAST
    if fast_command==CMD_BCR or fast_command==CMD_BCROCR: bx_counter = ORBITBCR
    return bx_counter

def count_orbit(i,fast_command):
    orbit_counter = int(i/ORBITLAST)
    if fast_command==CMD_BCROCR: orbit_counter = 0
    return orbit_counter

def generate_fast_commands(args):
    N = args.N
    
    fast_commands = np.array([CMD_IDLE] * N, dtype='object')

    if args.bcr:
        # assume bcr sent at BX=3513
        bcr_bxs = [i for i in range(len(fast_commands)) if i%ORBITLAST==ORBITBCR]
        # extra bcrs
        if args.extra_bcr:
            bcr_bxs += [2000]
        # missing bcrs
        if args.missing_bcr:
            bcr_bxs.pop(0)        
        fast_commands[bcr_bxs] = CMD_BCR

    if args.bocr:
        # assume ocr sent at BX=3513
        ocr_bxs = [i for i in range(len(fast_commands)) if i%ORBITLAST==ORBITBCR]
        fast_commands[ocr_bxs] = CMD_BCROCR

    if args.ecr and args.ecrBX!='':
        # assume ecr sent at unique globalBXs
        ecr_bxs = [int(ecr) for ecr in args.ecrBX.split(',')]
        fast_commands[ecr_bxs] = CMD_ECR

    L1a_bxs,L1a_name = generate_L1a_fast_commands(args)
    fast_commands[L1a_bxs] = CMD_L1A
    num_events = len(L1a_bxs)

    if args.ebr and args.ebrBX!='':
        # fill array with bxs up to 3BXs after l1as
        L1a_bxs_after4 = []
        for i in range(3):
            L1a_bxs_after4 += [bx+i+1 for bx in L1a_bxs if bx not in L1a_bxs_after4]
        # print('l1a bxs after 4 ',L1a_bxs_after4)
        ebr_bxs = [int(ebr) for ebr in args.ebrBX.split(',') if int(ebr) not in L1a_bxs_after4]
        fast_commands[ebr_bxs] = CMD_EBR
        
    # command - orbit - bx - globalBx
    commands = [{'fc': fast_command,
                 'orbit': count_orbit(i,fast_command),
                 'BX': count_bx(i,fast_command),
                 'globalBX': i}  for i,fast_command in enumerate(fast_commands)]
    
    return commands,L1a_name,num_events

def make_dataset(args,num_events):
    packet_counter = 0
    roc_buffer = []

    if args.physicsdata:
        from getElinkInputDataFromMC import loadMCData

        # try parsing the wafer coordinates
        try:
            subdet,zside,layer,waferu,waferv=eval(args.waferCoordinates)
        except:
            print('#'*20)
            print('#'*20)
            print(f'Unable to parse wafer coordinates ({args.waferCoordinates}) for (subdet,zside,layer,waferu,waferv)')
            print('   Falling back to default values')
            print('      (0,5,1,3,1)')
            print('#'*20)
            print('#'*20)
            subdet,zside,layer,waferu,waferv = 0,5,1,3,1

        # load dataframe, with formatted words
        mcDataDF = loadMCData(fName=args.fname, subdet=subdet, zside=zside, layer=layer, waferu=waferu, waferv=waferv)

        # get list of entries that are present in the dataframe
        # then pick a random set to use at the L1A data
        entryList = mcDataDF.index.levels[0].values
        l1Aevents = np.random.choice(entryList,num_events)

    for event_counter in range(num_events):
        words = DATAWORDS.split('_')

        # packet count: from 0 to 15 and then rolls over
        # 4 bit: 0000 to 1111 (from 0 to 15)
        if packet_counter==16: packet_counter = 0
        
        data_by_link = dict()
        for link_counter in range(NELINKS): # link counter 
            data_by_link[link_counter] = []

            # word counter: 0-41
            for word_counter,word_type in enumerate(words):
                
                if word_type=='HDR':
                    word = 'HDR' # place-holder, so that we can replace with bx and orbit when L1A is called
                elif word_type=='CM':
                    if args.physicsdata or args.zerodata:
                        word = '10'
                        word += '{0:010b}'.format(0)
                        word += '{0:010b}'.format(random.getrandbits(10)) # ADC-CM0
                        word += '{0:010b}'.format(random.getrandbits(10)) # ADC-CM1
                    else:
                        word = '{0:04b}'.format(packet_counter) # 4b count number
                        word += '{0:04b}'.format(link_counter+1) # 4b elink number
                        word += '{0:08b}'.format(word_counter) # 8b packet word
                        word += '{0:04b}'.format(packet_counter)
                        word += '{0:04b}'.format(link_counter+1)
                        word += '{0:08b}'.format(word_counter)
                elif word_type=='IDLE':
                    word = '{0:032b}'.format(IDLEWORD_HEX) # assume non-bc0
                elif word_type=='CRC':
                    # add random CRC bits for now (todo: implement real CRC calculation)
                    word = '{0:032b}'.format(random.getrandbits(32)) 
                else:
                    if args.zerodata:
                        # a zero 32-bit word                                                                                                                                                                                                            
                        word = '{0:032b}'.format(0)
                    elif args.physicsdata:
                        word = mcDataDF.loc[(l1Aevents[event_counter],link_counter),word_type]
                    else:
                        word = '{0:04b}'.format(packet_counter)
                        word += '{0:04b}'.format(link_counter+1)
                        word += '{0:08b}'.format(word_counter)
                        word += '{0:04b}'.format(packet_counter)
                        word += '{0:04b}'.format(link_counter+1)
                        word += '{0:08b}'.format(word_counter)

                # if word_type!='HDR' and word_type!='IDLE':
                #     print('packet counter ',packet_counter,' link counter ',link_counter+1,' word counter ',word_counter,' word ',word)
                # else:
                #     print('word_type ',word_type)
                data_by_link[link_counter].append(word)

        # increase packet counter after a full 12 e-link packet is sent
        packet_counter += 1
                
        roc_buffer.append(data_by_link)

    return roc_buffer

def make_eportRX_input(args):
    
    # produce idle fast commands w. other fast commands
    commands, L1a_name, num_events = generate_fast_commands(args)
    
    # output data
    channels = ['Hard reset', 'Soft reset']
    for link_counter in range(NELINKS): channels.append('Aligner Ch%i (32 bit)'%link_counter)
    channels.append('Fast Command (8 bit)')

    # start
    start_by_channel = dict.fromkeys(channels)
    start_by_channel['Hard reset'] = [1]
    start_by_channel['Soft reset'] = [1]
    for link_counter in range(NELINKS): start_by_channel['Aligner Ch%i (32 bit)'%link_counter] = [IDLEWORD]
    start_by_channel['Fast Command (8 bit)'] = [CMD_IDLE]

    # reset
    reset_by_channel = dict.fromkeys(channels)
    reset_by_channel['Hard reset'] = [0] * 3
    reset_by_channel['Soft reset'] = [1] * 3
    for link_counter in range(NELINKS): reset_by_channel['Aligner Ch%i (32 bit)'%link_counter] = [IDLEWORD] * 3
    reset_by_channel['Fast Command (8 bit)'] = [CMD_IDLE] * 3

    # end
    end_by_channel = dict.fromkeys(channels)
    end_by_channel['Hard reset'] = [1]
    end_by_channel['Soft reset'] = [1]
    for link_counter in range(NELINKS): end_by_channel['Aligner Ch%i (32 bit)'%link_counter] = ['{0:08X}'.format(int('{0:032b}'.format(ONEWORD_HEX),base=2))]
    end_by_channel['Fast Command (8 bit)'] = [CMD_ALLONE] 
    
    # dataDAQ
    data_by_channel = dict.fromkeys(channels)
    data_by_channel['Hard reset'] = []
    data_by_channel['Soft reset'] = []
    data_by_channel['Fast Command (8 bit)'] = []
    roc_buffer_by_link = make_dataset(args,num_events)

    # event buffer: contains the index of the event number to read from the roc_buffer
    event_buffer = []

    # delay_buffer: contians when to read events in the event_buffer
    delay_buffer = []

    # the data that ECON sees
    roc_data_by_link = dict()
    for link_counter in range(NELINKS): roc_data_by_link[link_counter] = []

    # counters
    roc_counter = 0
    buffer_counter = 0
    event_counter = 0

    # loop over fast commands (or BX)
    num_bx = args.N
    bx_counter = 0
    while bx_counter < num_bx:
        command_ = commands[bx_counter]['fc'] if len(commands)>bx_counter else CMD_IDLE
        bx_ = commands[bx_counter]['BX'] if len(commands)>bx_counter else count_bx(bx_counter,command_)

        # fill in other columns
        data_by_channel['Hard reset'].append(1)
        data_by_channel['Soft reset'].append(1)
        data_by_channel['Fast Command (8 bit)'].append(command_)
        
        # if L1A then pull event out of daq buffer to event buffer
        if command_ == CMD_L1A:
            # set delay
            if len(event_buffer)==0:
                # if buffer is empty: get evt in delay time (e.g. 7BX)
                delay=args.delay
                start=bx_counter+delay
            else:
                # if buffer is not empty:
                #    if the length(buffer) < delay_time: get evt in delay time (e.g. 7BX)
                #    else: get evt in (delay time - (words to end))
                num_words_until_end = NWORDS-len(event_buffer[-1])
                if num_words_until_end >= args.delay:
                    delay=0
                else:
                    delay=args.delay-num_words_until_end
                start=delay_buffer[-1]['start']+NWORDS+delay
                
            print('L1A at BX: ',bx_counter,' Events in buffer: ',len(event_buffer),' Latency delay: ',delay,' Start reading this evt at: ',start,' End at ',start+NWORDS-1)

            # appends empty list that later fills
            event_buffer.append([])
            # contains current BX, BX at which we should start reading the event (start) and finish reading the event (end), and the index of the event to pull from the roc_buffer
            # and # of BXs that will take to read this event (bx_counter + delay + nWords)
            delay_buffer.append({'globalBX':bx_counter,
                                 'start':start,
                                 'end':start+NWORDS-1,
                                 'event':roc_counter
                                 })
            # print('events in buffer',event_buffer)

            # increase roc buffer counter every time we see an l1a
            roc_counter +=1
            
        # if ECR, then reset the event counter 
        if command_ == CMD_ECR:
            event_counter = 0

        # if EBR, then reset the event buffer
        if command_ == CMD_EBR:
            #print('send ebr ',bx_counter,event_buffer,' buffer_counter ',buffer_counter)
            if buffer_counter>0:
                event_buffer = [event_buffer[0]]
                delay_buffer = [delay_buffer[0]]
                event_counter = 0
            else:
                event_buffer = [] # not clear just get the first out?
                delay_buffer = []
                event_counter = 0
            #print(event_buffer)

        # replace num_bx with the last event to read
        if len(delay_buffer)>0 and delay_buffer[-1]['end']>=args.N:
            num_bx = delay_buffer[-1]['end']+1
            
        # read event buffer, read one word in one BX
        is_reading_buffer = False
        if len(event_buffer)>0:
            bx_read = delay_buffer[0]['globalBX']
            start_read = delay_buffer[0]['start']
            end_read = delay_buffer[0]['end']
            event_read = delay_buffer[0]['event']
            
            bx = commands[bx_read]['BX'] 
            orbit = commands[bx_read]['orbit']

            if bx_counter>=start_read and bx_counter<=end_read:
                # print(bx_counter,'reading',bx_read,' length of evt buffer ',len(event_buffer[0]))

                # convert to hex
                for link_counter in range(NELINKS):
                    word = roc_buffer_by_link[event_read][link_counter][buffer_counter]
                    if word=='HDR':
                        word ='0101'
                        word += '{0:012b}'.format(bx & 0b111111111111) # bx
                        word += '{0:06b}'.format(event_counter & 0b111111) # event
                        word += '{0:03b}'.format(orbit & 0b111) # orbit
                        word += '{0:01b}'.format(random.getrandbits(1)) #H1
                        word += '{0:01b}'.format(random.getrandbits(1)) #H2
                        word += '{0:01b}'.format(random.getrandbits(1)) #H3
                        word += '0101'

                    # debug for elink2
                    # if link_counter==2: print(word)
                    word = '{0:08X}'.format(int(word,base=2))
                    roc_data_by_link[link_counter].append(word)

                buffer_counter +=1
                is_reading_buffer = True

                event_buffer[0].append( roc_data_by_link[0][-1] )

                if len(event_buffer[0])==NWORDS:
                    # increase event counter
                    event_counter +=1
                    
                    event_buffer.pop(0)
                    delay_buffer.pop(0)

                    # reset buffer counter
                    buffer_counter=0
                
        if not is_reading_buffer:
            for link_counter in range(NELINKS):
                idle_word = IDLEWORD_BC0 if bx_==0 else IDLEWORD
                roc_data_by_link[link_counter].append(idle_word)

        bx_counter+=1 # end while loop
                    
    # append channel data
    for link_counter in range(NELINKS):
        data_by_channel['Aligner Ch%i (32 bit)'%link_counter] = roc_data_by_link[link_counter]

    # creating dataframes
    df_start = pd.DataFrame.from_dict(start_by_channel)
    df_reset = pd.DataFrame.from_dict(reset_by_channel)
    df_data = pd.DataFrame.from_dict(data_by_channel)
    df_end = pd.DataFrame.from_dict(end_by_channel)

    # write csv
    file_name = "ROC_DAQ_%ifc_"%args.N

    if L1a_name!='':
        file_name += L1a_name
    if args.bcr:
        file_name += "_wbcr"
        if args.missing_bcr:
            file_name += "_missingbcr"
        if args.extra_bcr:
            file_name += "_extrabcr"
    if args.bocr:
        file_name += "_wbocr"
    if args.ecr and args.ecrBX!='':
        file_name += "_wecrBX" + args.ecrBX.replace(',','-')
    if args.ebr and args.ebrBX!='':
        file_name += "_webrBX" + args.ebrBX.replace(',','-')
    if args.physicsdata:
        file_name += "_physicsdata"
        
    output_file = open('rocData/%s.csv'%file_name, 'w')
    description = "# Provides a simple reset and then %i fast commands"%num_bx
    if L1a_name!='':
        description+=" with %i event packets (with %i BXs of delay)\n"%(event_counter,args.delay)
        description += "# The data idle word will contain the special 0x9 header for BC0\n"
    else:
        description+="\n"

    output_file.write(description)
    output_file.write("# "+",".join(channels)+"\n")
    output_file.write("# start\n")
    df_start.to_csv(output_file, index=False, header=False)
    output_file.write("# reset\n")
    df_reset.to_csv(output_file, index=False, header=False)
    output_file.write("# %i fast commands \n"%num_bx)
    df_data.to_csv(output_file, index=False, header=False)
    output_file.write("# end\n")
    df_end.to_csv(output_file, index=False, header=False)
    output_file.close()
    
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
    parser.add_argument('--nL1a', type=str, default='', dest="nL1a", help="Length of L1A patterns sent")
    parser.add_argument('--L1a_freq', type=str, default='', dest="L1a_freq", help="Send L1As with a frequency of 1 in L1A_freq")
    parser.add_argument('--zero-data',  action='store_true', default=False, dest="zerodata", help="send zero data in L1A")
    parser.add_argument('--physics-data',  action='store_true', default=False, dest="physicsdata", help="use physics data from MC in L1A")
    
    parser.add_argument('--waferCoor', type=str, default="0,1,5,3,1", dest='waferCoordinates', help='coordinates of wafer to data to load from MC: subdet,zside,layer,waferU,waferV; as a comma separated list')
    parser.add_argument('--fname', type=str, default='', dest="fname", help="MC filename")
    
    args = parser.parse_args()

    make_eportRX_input(args)
