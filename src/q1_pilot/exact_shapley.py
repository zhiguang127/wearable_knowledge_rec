"""Standard exact Shapley enumeration, a reference, not a new algorithm."""
from math import comb

def exact(values,n):
    if len(values)!=1<<n: raise ValueError('incomplete coalition table')
    return [sum((values[m|1<<i]-values[m])/(n*comb(n-1,m.bit_count()))
        for m in range(1<<n) if not m & (1<<i)) for i in range(n)]

def efficiency(phi,values): return abs(sum(phi)-(values[-1]-values[0]))
