# ECOND_ROC_Emulator
Emulating HGCROC for ECOND 

### Emulating datasets
- N: number of orbits
- sequence: string with sequence of L1as e.g.:
```
python3 simulateInputECOND.py -N 10692 --bcr --sequence random --zerodata
python3 simulateInputECOND.py -N 10692 --bcr --sequence fixed --L1a_freq 1 --nL1a 10 --zerodata
```
- to send non-zero data:
```
python3 simulateInputECOND.py -N 10692 --bcr --sequence fixed --L1a_freq 50 --nL1a 3
```
note that `fixed` needs L1a_freq and nL1a

- ecr: event counter reset, e.g.:
```
python3 simulateInputECOND.py -N 10692 --bcr --sequence random --ecr --ecrBX 9050 --zerodata
```
- ebr: event buffer reset, e.g.
  - 10692 fc with 2 L1as sent at a fixed frequency (50 BX) and a EBR sent after those events finish transmitting to ECON
  
  ```python3 simulateInputECOND.py -N 10692 --bcr --sequence fixed --L1a_freq 50 --nL1a 1 --ebr --ebrBX 150 --zerodata```
  - 10692 fc with 3 L1as sent at a fixed frequency (50 BX) and a EBR sent in between those events 
  
  ```python3 simulateInputECOND.py -N 10692 --bcr --sequence fixed --L1a_freq 50 --nL1a 2 --ebr --ebrBX 98 --zerodata```
  
  - 10692 fc with 3 L1as sent at a fixed frequency (50 BX) and a EBR sent after the 2nd L1a is sent but before the ROC has begun transmitting that event. Then I send another L1A later.
  
  ```python3 simulateInputECOND.py -N 10692 --bcr --sequence fixed --L1A_freq 50 --nL1a 2 --ebr --ebrBX 102 --zerodata```
  
  - 10692 fc with 3 L1as sent at a fixed frequency (50 BX) and a EBR sent after the 2nd L1a is sent and after the ROC has begun transmitting that event (the ROC is in the middle of reading that event - has only read word 1). Then I send another L1a later.
  
  ```python3 simulateInputECOND.py -N 10692 --bcr --sequence fixed --L1a_freq 50 --nL1a 2 --ebr --ebrBX 108 --zerodata```
