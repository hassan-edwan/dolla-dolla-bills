import pandas as pd, numpy as np, csv, sys
doc={r['Acronym']:r for r in csv.DictReader(open(sys.argv[1]))}
sigs=['BMdec','EP','SP','CF','EntMult','GP','OperProfRD','CBOperProf','roaq','AssetGrowth','InvestPPEInv','NOA','dNoa','Accruals','PctAcc','TotalAccruals','ShareIss1Y','ShareIss5Y','CompEquIss','XFIN','NetEquityFinance','NetPayoutYield','EarningsSurprise','AnnouncementReturn','RevenueSurprise','EarningsStreak','EarnSupBig','PS','FailureProbability','OScore','RD','RDcap','RDAbility','ChTax','ChAssetTurnover','Cash','OPLeverage','GrSaleToGrInv','ChEQ','InvGrowth','grcapx']
def st(s):
    s=s.dropna()
    if len(s)<24: return (np.nan,np.nan,len(s))
    return (s.mean(), s.mean()/s.std()*np.sqrt(len(s)), len(s))
out=[]
dd={n:pd.read_parquet(n+'.parquet') for n in ['op','ex_nyse_p20_me','deciles_vw']}
for n,d in dd.items(): d['y']=d.date.dt.year
for k in sigs:
    if k not in doc: print('nodoc',k); continue
    s0,s1=int(doc[k]['SampleStartYear']),int(doc[k]['SampleEndYear']); pub=int(doc[k]['Year'])
    row=[k]
    for n,d in dd.items():
        x=d[d.signalname==k]
        if x.empty: row+=['na']*8; continue
        ls=x[x.port=='LS'].set_index('date').ret
        y=ls.index.year
        a=st(ls[(y>=s0)&(y<=s1)]); b=st(ls[y>pub]); c=st(ls[y>=2015])
        if n=='op':
            hr=(ls[y>=2015]>0).mean(); row+=[f'{a[0]:.2f}({a[1]:.1f})',f'{b[0]:.2f}({b[1]:.1f})',f'{c[0]:.2f}({c[1]:.1f})',f'{hr:.0%}']
            # long leg: top portfolio by sign minus average of all non-LS ports, 2015+ and post-pub
            p=x[x.port!='LS'].pivot(index='date',columns='port',values='ret')
            ports=sorted(p.columns)
            sign=float(doc[k]['Sign'])
            longp=ports[-1]
            shortp=ports[0]
            avg=p.mean(axis=1)
            ll=(p[longp]-avg); sl=(avg-p[shortp])
            yy=p.index.year
            l1=st(ll[yy>pub]); s1_=st(sl[yy>pub]); l2=st(ll[yy>=2015])
            row+=[f'{l1[0]:.2f}({l1[1]:.1f})',f'{s1_[0]:.2f}({s1_[1]:.1f})',f'{l2[0]:.2f}({l2[1]:.1f})']
        else:
            row+=[f'{b[0]:.2f}({b[1]:.1f})',f'{c[0]:.2f}({c[1]:.1f})']
    out.append(row)
hdr='sig|OP_insample|OP_postpub|OP_2015_25|hit2015|OP_longleg_vsavg_postpub|OP_shortleg_postpub|OP_longleg_2015|exMicro_postpub|exMicro_2015|VWdec_postpub|VWdec_2015'
print(hdr)
for r in out: print('|'.join(map(str,r)))
