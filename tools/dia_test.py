import time, torch, soundfile as sf, sys
from dia.model import Dia
t=time.time()
m=Dia.from_pretrained("nari-labs/Dia-1.6B-0626", compute_dtype="float16", device=torch.device("mps"))
print("loaded",round(time.time()-t),"s",flush=True)
text="[S1] Hey Rob. I took a look at Flip Aquatics' ads in the Meta Ad Library. I can see nine active ads right now. [S2] Okay."
t=time.time()
torch.manual_seed(7)
a=m.generate(text,use_torch_compile=False,verbose=True,max_tokens=900)
d=len(a)/44100
print("audio",round(d,1),"s in",round(time.time()-t),"s",flush=True)
sf.write(sys.argv[1],a,44100)
