# ECOND_ROC_Emulator
Emulating HGCROC for ECOND 

### Emulating datasets
- N: number of orbits
- sequence: string with sequence of L1As e.g.:
```
python3 simulateInputECOND.py -N 10692 --bcr --sequence random
python3 simulateInputECOND.py -N 10692 --bcr --sequence fixed --L1A_freq 1 --nL1A 10
```
note that `fixed` needs L1A_freq and nL1A

- ecr: event counter reset, e.g.:
```
python3 simulateInputECOND.py -N 10692 --bcr --sequence random --ecr --ecrBX 9050
```
- ebr: event buffer reset, e.g.
  - 10692 fc with 2 L1As sent at a fixed frequency (50 BX) and a EBR sent after those events finish transmitting to ECON
  
  ```python3 simulateInputECOND.py -N 10692 --bcr --sequence fixed --L1A_freq 50 --nL1A 1 --ebr --ebrBX 150```
  - 10692 fc with 3 L1As sent at a fixed frequency (50 BX) and a EBR sent in between those events 
  
  ```python3 simulateInputECOND.py -N 10692 --bcr --sequence fixed --L1A_freq 50 --nL1A 2 --ebr --ebrBX 98```
  
  - 10692 fc with 3 L1As sent at a fixed frequency (50 BX) and a EBR sent after the 2nd L1A is sent but before the ROC has begun transmitting that event. Then I send another L1A later.
  
  ```python3 simulateInputECOND.py -N 10692 --bcr --sequence fixed --L1A_freq 50 --nL1A 2 --ebr --ebrBX 102```
  
  - 10692 fc with 3 L1As sent at a fixed frequency (50 BX) and a EBR sent after the 2nd L1A is sent and after the ROC has begun transmitting that event (the ROC is in the middle of reading that event - has only read word 1). Then I send another L1A later.
  
  ```python3 simulateInputECOND.py -N 10692 --bcr --sequence fixed --L1A_freq 50 --nL1A 2 --ebr --ebrBX 108```
