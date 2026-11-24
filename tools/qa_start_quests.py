#!/usr/bin/env python3
"""Audit the book entry (GTIA-D-426): the 0.0 First Fire chapter and the Welcome chapter, the author's Welcome quests and the Prism copy."""
import sys
import tomllib
from pathlib import Path
import re,json,copy,shutil,datetime
class Raw(str): pass
class Parser:
 def __init__(self,s): self.t=re.findall(r'"(?:\\.|[^"\\])*"|[{}\[\]:,]|[^\s{}\[\]:,]+',re.sub(r'(?m)^\s*//.*$','',s)); self.i=0
 def pop(self): t=self.t[self.i]; self.i+=1; return t
 def value(self):
  t=self.pop()
  if t=='{':
   d={}
   while self.t[self.i]!='}':
    k=self.pop(); k=json.loads(k) if k.startswith('"') else k
    assert self.pop()==':'
    assert k not in d
    d[k]=self.value()
    if self.t[self.i]==',': self.pop()
   self.pop(); return d
  if t=='[':
   a=[]
   while self.t[self.i]!=']':
    a.append(self.value())
    if self.t[self.i]==',':self.pop()
   self.pop(); return a
  return json.loads(t) if t.startswith('"') else Raw(t)
 def parse(self):
  d=self.value(); assert self.i==len(self.t); return d


import hashlib,itertools,math,argparse

def audit():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--prism',type=Path,default=Path.home()/'.local/share/PrismLauncher/instances/GTIA (full pack)/minecraft/config/ftbquests/quests')
 ap.add_argument('--check-prism',action='store_true',help='also require the installed copy to be byte-identical to the source')
 args=ap.parse_args()
 pack=Path(__file__).resolve().parents[1]
 source=pack/'config/ftbquests/quests'
 legacy=pack/'quests-src/legacy'
 backup=legacy/'start-author-2026-09-30'
 sys.path.insert(0,str(pack/'tools')); from questgen import ident
 # GTIA-D-426: the Start chapter is retired (sources in quests-src/legacy/); 0.0 First Fire opens the book and the
 # Welcome, still cut from the author's Start, links to it.
 assert not (source/'chapters/start.snbt').exists(),'The retired Start chapter must not be generated'
 first=Parser((source/'chapters/type0_0_first_fire.snbt').read_text()).parse()
 w=Parser((source/'chapters/welcome.snbt').read_text()).parse()
 chapter_of={q['id']:'type0_0' for q in first['quests']}|{q['id']:'welcome' for q in w['quests']}
 qs={q['id']:q for q in first['quests']+w['quests']}
 assert len(qs)==len(first['quests'])+len(w['quests']),'A quest id is in both chapters'
 old=Parser((backup/'chapters/start.snbt').read_text()).parse()
 # GTIA-D-436: one mode only; no modes chapter and no quest gated by a mode.
 assert not (source/'chapters/modes.snbt').exists(),'The modes chapter must not be generated'
 by_title={q.get('title'):q['id'] for q in Parser((legacy/'start.original.snbt').read_text()).parse()['quests']}
 meta=tomllib.loads((legacy/'start.toml').read_text())
 # Start steps whose author rewards gave way to a starting kit (GTIA-D-279/D-436).
 kit_of={by_title[s['title']]:ident(f"quest:start:{s['key']}_normal") for s in meta['kit_reward']}
 assert len(old['quests'])==29  # the 29 approved quests (The Research Tree was removed with GTIA-D-226)
 ids=[first['id'],w['id']]
 for q in qs.values():
  ids.append(q['id'])
  assert q['title'] and q['subtitle'] and q['icon']
  assert len(q['subtitle'])<=70
  assert any(q['description']) and all(isinstance(t,str) and t.isascii() for t in q['description'])
  assert all(dep in qs and dep!=q['id'] for dep in q.get('dependencies',[]))
  assert all(chapter_of[dep]==chapter_of[q['id']] for dep in q.get('dependencies',[])),'A dependency crosses chapters'
  assert not any(w in line for line in q['description']+[q['title'],q['subtitle']] for w in ('Journey','Normal world','typeomega rules')),f'Mode text left: {q["title"]}'
  assert q['tasks']
  for t in q['tasks']:
   ids.append(t['id']);assert t['title'] if t['type']!='item' else True
   if t['type']=='item':
    assert t['consume_items']=='false' and t['match_nbt']=='false'
    assert isinstance(t['item'],str) and ':' in t['item']
   else:assert t['type']=='checkmark'
  ids.extend(r['id'] for r in q.get('rewards',[]))
  for axis in ['x','y']:assert float(str(q[axis]).rstrip('d'))*4%1==0
 assert len(ids)==len(set(ids)), 'Duplicate object ID'
 visiting=set();visited=set()
 def visit(i):
  assert i not in visiting,'Dependency cycle'
  if i in visited:return
  visiting.add(i)
  for dep in qs[i].get('dependencies',[]):
   if dep in qs:visit(dep)
  visiting.remove(i);visited.add(i)
 for i in qs:visit(i)
 def number(q,k):return float(str(q[k]).rstrip('d'))
 for a,b in itertools.combinations(qs.values(),2):
  if chapter_of[a['id']]!=chapter_of[b['id']]:continue
  assert math.hypot(number(a,'x')-number(b,'x'),number(a,'y')-number(b,'y'))>(number(a,'size')+number(b,'size'))/2, 'Overlapping nodes'
 # The author's Welcome quests keep id, task ids and item rewards (the rest of the old Start lives in quests-src/legacy/).
 renamed={f['new_title']:f['title'] for f in meta.get('text_fix',[]) if f.get('new_title')}
 moved={renamed.get(t,t) for t in meta['welcome']['titles']}
 kept=[a for a in old['quests'] if a['id'] in qs]
 assert {by_title[t] for t in moved}=={a['id'] for a in kept} and len(kept)==len(moved)
 for a in kept:
  b=qs[a['id']]
  assert chapter_of[a['id']]=='welcome'
  assert {t['id'] for t in a['tasks']}=={t['id'] for t in b['tasks']}
  removed={x['item'] for x in meta.get('reward_removal',[]) if by_title.get(x['title'])==a['id']}
  item_id=lambda r:r.get('item',{}).get('id') if isinstance(r.get('item'),dict) else r.get('item')
  if removed:a=dict(a,rewards=[r for r in a.get('rewards',[]) if item_id(r) not in removed])
  if any(r['type']=='item' for r in a.get('rewards',[])):
   assert a['rewards']==b['rewards'] or (not b['rewards'] and kit_of.get(a['id']) in qs),'Author item reward changed'
 # 0.0 is the entry of the book: the Welcome links to it, it depends on nothing, and everything in it hangs from it.
 entry=ident('quest:type0_0_first_fire:entry')
 assert entry in qs and chapter_of[entry]=='type0_0' and not qs[entry].get('dependencies'),'0.0 needs a free entry quest'
 assert [l['linked_quest'] for l in w['quest_links']]==[entry],'The Welcome must link to the 0.0 entry'
 welcome=by_title['Welcome to Infinity Ascension']
 assert welcome in qs and chapter_of[welcome]=='welcome' and not qs[welcome].get('dependencies')
 free_kits={ident(f"quest:start:{m['key']}{suffix}") for m in meta['kit_reward'] for suffix in ('_normal','_both')}
 def root_of(i,seen=()):
  deps=[d for d in qs[i].get('dependencies',[]) if d in qs]
  return {i} if not deps else set().union(*(root_of(d) for d in deps))
 for i,q in qs.items():
  if i in free_kits:continue  # the Welcome kits complete with their step's task and have no road (GTIA-D-279)
  assert root_of(i)=={entry if chapter_of[i]=='type0_0' else welcome},f'Not reachable from the chapter entry: {q["title"]}'
 # 0.0 hands over to 0.1 (Steam and Steel) and has its first machine step.
 nxt=ident('quest:type0_1_steam_steel:entry')
 assert [l['linked_quest'] for l in first['quest_links']]==[nxt],'0.0 must link to the 0.1 entry'
 assert first['order_index']=='2' or str(first['order_index'])=='2'
 for rel in ['chapters/type0_0_first_fire.snbt','chapters/welcome.snbt','data.snbt','chapter_groups.snbt']:
  Parser((source/rel).read_text()).parse()
  if args.check_prism:assert (source/rel).read_bytes()==(args.prism/rel).read_bytes(),f'Prism mismatch: {rel}'
 print(f'Entry OK: {len(qs)} quests (0.0: {len(first["quests"])}, Welcome: {len(w["quests"])}), {len(ids)} unique chapter/quest/task/reward IDs, no cycles or overlaps; titles, descriptions, icons, the author\'s Welcome rewards and the Welcome -> 0.0 -> 0.1 links.')
 print('type0_0_first_fire.snbt SHA-256:',hashlib.sha256((source/'chapters/type0_0_first_fire.snbt').read_bytes()).hexdigest())

if __name__=='__main__':audit()
