import uproot
import pandas as pd

import awkward as ak

# load and skim dataframe a few events at a time (more memory efficient)
def getDF(_tree, entrysteps=10, subdet=0, zside=1, layer=9, u=3, v=3):
    t = []
    branches=['hgcdigi_subdet','hgcdigi_zside','hgcdigi_layer','hgcdigi_waferu','hgcdigi_waferv','hgcdigi_cellu','hgcdigi_cellv','hgcdigi_wafertype','hgcdigi_data_BX1','hgcdigi_isadc_BX1','hgcdigi_data_BX2','hgcdigi_isadc_BX2','hgcdigi_toa_BX2']

    x = _tree.arrays(branches)
    selection = (x['hgcdigi_subdet']==subdet) & (x['hgcdigi_zside']==zside) & (x['hgcdigi_layer']==layer) & (x['hgcdigi_waferu']==u) & (x['hgcdigi_waferv']==v)

    return ak.to_pandas(x[selection])


def formatData(x):
    isTOT = 1-x.isadc
    
    tp = 0
    # assign tp randomly??? right now, just use isadc-1
    tp = 1-x.isadcm1
    
    # build 32 bit word
    data = (isTOT<<31) + (tp<<30) + (x.adcm1<<20) + (x.cellData<<10) + (x.toa)
    return data


def loadMCData(fName = 'root://cmseos.fnal.gov//store/user/lpchgcal/ConcentratorNtuples/L1THGCal_Ntuples/DAQ_Data/TTbar_SampleFile/ntuple.root',
               outputName=None,
               subdet=0,
               zside=1,
               layer=5,
               waferu=3,
               waferv=1,
               dataType='bin',
               returnCellDF=False):


    #load tree
    uproot.open.defaults["xrootd_handler"] = uproot.MultithreadedXRootDSource
    _tree = uproot.open(fName)['hgcalTriggerNtuplizer/HGCalTriggerNtuple']

    df = getDF(_tree, 5, subdet=subdet, zside=zside, layer=layer, u=waferu, v=waferv)
    df.columns = ['subdet','zside','layer','waferu','waferv','cellu','cellv','wafertype','adcm1','isadcm1','cellData','isadc','toa']

    df['HDM'] = df.wafertype==0
    isHDM = df.HDM.all()

    df.reset_index('subentry',drop=True,inplace=True)
    df.loc[df.toa==-1,'toa'] = 0

    #convert the 3 values into a formatted 32 bit word
    df['FormattedData'] = df.apply(formatData,axis=1)

    #duplicate specific cells and call them calibration cells
    #  give calibration cells u/v values that are negative
    calCells = pd.read_csv('geomInfo/calibrationCells.csv')
    calCellData = df.reset_index().merge(calCells,on=['HDM','cellu','cellv']).fillna(0)
    calCellData[['cellu','cellv']] = calCellData[['U','V']]

    #concatenate the calibration to the dataframe 
    df = pd.concat([df.reset_index(),calCellData.drop(['isCal','U','V'],axis=1)])

    #merge with eRx link mapping
    linkMap = pd.read_csv('geomInfo/eLinkInputMapFull.csv')
    df = df.merge(linkMap,on=['HDM','cellu','cellv']).set_index(['entry','eLink','linkChannel'])
    df.sort_index(inplace=True)

    if dataType.lower()=='hex':
        df['FormattedData'] = df.FormattedData.apply(lambda x: '{0:08x}'.format(x) )
        dfLinks = df.FormattedData.unstack(fill_value='00000000')
    elif dataType.lower()=='bin':
        df['FormattedData'] = df.FormattedData.apply(lambda x: '{0:032b}'.format(x) )
        dfLinks = df.FormattedData.unstack(fill_value='0'*32)
    else:
        dfLinks = df.FormattedData.unstack(fill_value=0)

    dfLinks.columns = [f'CH{i}' for i in range(37)]

    if not outputName is None:
        dfLinks.to_csv(outputName)

    if returnCellDF:
        return dfLinks, df

    else:
        return dfLinks


if __name__=="__main__":
    dfLinks, df = loadMCData(returnCellDF=True)
