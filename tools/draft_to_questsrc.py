#!/usr/bin/env python3
"""Turn the approved Type 0 layout drafts into quest sources for questgen.py (GTIA-D-421: development beta).

    draft_to_questsrc.py [--drafts DIR]    write quests-src/type0_*.toml and add the text to quests-src/lang/

A draft is a Python file with TITLE and Q = [(id, label, role, size, x, y, deps, item)]. The label is the Portuguese
title; English and Chinese titles come from tools/data/type0_titles.tsv, tip text from tools/data/type0_tips.tsv.
A dependency "~x" draws no line; "t0N:x" points at quest x of draft N. The first quest becomes the chapter entry and
the "exit" role its exit. Items joined by "|" become one task each; tips and guides are checkmarks. Rerunning gives
the same files, so the drafts stay the source until the chapters are edited by hand.
"""

from __future__ import annotations

import argparse
import json
import re
import runpy
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]
SRC = PACK / "quests-src"
DATA = Path(__file__).resolve().parent / "data"
REGISTRY = PACK / "manifest" / "registry" / "pack"
DRAFTS = PACK.parent / "design" / "quests" / "type_omega"

# prefix, draft, quest-src file, English title, Chinese title
CHAPTERS = [
    ("t00", "tipo0_00_02/t00_primeiro_fogo.py", "type0_0_first_fire", "0.0 · First Fire", "0.0 · 初火"),
    ("t01", "tipo0_00_02/t01_vapor_aco.py", "type0_1_steam_steel", "0.1 · Steam and Steel", "0.1 · 蒸汽与钢"),
    ("t02", "tipo0_03_04/t02_eletricidade.py", "type0_2_electricity", "0.2 · Electricity", "0.2 · 电力"),
    ("t03", "tipo0_03_04/t03_alto_forno.py", "type0_3_blast_furnace", "0.3 · Blast Furnace", "0.3 · 高炉"),
    ("t04", "tipo0_03_04/t04_mv.py", "type0_4_medium_voltage", "0.4 · Medium Voltage", "0.4 · 中压"),
    ("t05", "tipo0_05_08/t05_hv.py", "type0_5_end_of_mv", "0.5 · End of MV", "0.5 · 中压末期"),
    ("t06", "tipo0_05_08/t06_rede.py", "type0_6_power_grid", "0.6 · Power Grid", "0.6 · 电网"),
    ("t07", "tipo0_05_08/t07_lua.py", "type0_7_moon", "0.7 · Moon", "0.7 · 月球"),
    ("t08", "tipo0_05_08/t08_fusao.py", "type0_8_fusion", "0.8 · Fusion", "0.8 · 聚变"),
]

# EN: draft role -> FTB shape (GTO convention, D-409) and the questgen role that sets "optional".
# PT: papel do rascunho -> forma no FTB (convenção do GTO, D-409) e o papel do questgen que marca "opcional".
# ZH: 草稿角色 -> FTB 形状（GTO 惯例，D-409），以及决定“可选”的 questgen 角色。
SHAPES = {"hub": "circle", "item": "circle", "machine": "hexagon", "exit": "hexagon", "multi": "gear",
          "guide": "pentagon", "tip": "diamond", "bridge": "octagon"}
ROLE = {"tip": "hint"}

SUBTITLE = {  # role -> (en, pt, zh)
    "entry": ("Chapter start", "Início do capítulo", "章节开始"),
    "hub": ("Milestone", "Marco", "里程碑"),
    "item": ("Material", "Material", "材料"),
    "machine": ("Machine", "Máquina", "机器"),
    "multi": ("Multiblock", "Multibloco", "多方块"),
    "tip": ("Tip", "Dica", "提示"),
    "guide": ("Guide", "Guia", "指南"),
    "bridge": ("Bridge", "Ponte", "桥接"),
    "exit": ("Chapter exit", "Saída do capítulo", "章节出口"),
}

# EN: ids the drafts propose that the pack does not register yet (core work, D-406 to D-424). The quest becomes a
#     checkmark with a stand-in icon.
# PT: ids propostos nos rascunhos que o pack ainda não registra (trabalho do core, D-406 a D-424). A quest vira
#     checkmark com ícone substituto.
# ZH: 草稿中提出但整合包尚未注册的 ID（核心模组待办，D-406 至 D-424）。任务改为勾选并使用替代图标。
STAND_IN = {
    "typeomega:mars_probe": "gtceu:ev_sensor",
    "typeomega:mars_survey_data": "gtceu:data_orb",
}
STAND_IN_TASK: set[str] = set()  # stand-ins good enough to ask for as the task itself
# Draft id -> the id the core registered under another name.
ID_ALIAS = {"typeomega:silica_aerogel": "typeomega:silica_aerogel_dust"}

# Tasks that are not "hold the item". (chapter, id) -> task list
SPECIAL_TASKS = {("t07", "pouso"): [{"dimension": "ad_astra:moon"}]}

# EN: the minimal rewards the decisions name: Coke Oven gives coal (D-411), the Terminal gives the Nexus Structure
#     Terminal (D-406/D-411), the Personal Dimension gives its two portals (D-408).
# PT: as recompensas mínimas que as decisões citam: Coke Oven dá carvão (D-411), o Terminal dá o Terminal de
#     Estruturas do Nexus (D-406/D-411), a Dimensão Pessoal dá os dois portais (D-408).
# ZH: 决策中指定的最少奖励：焦炉给煤（D-411），终端给 Nexus 结构终端（D-406/D-411），个人维度给两个传送门（D-408）。
REWARDS = {
    ("t01", "coke_oven"): [{"item": "minecraft:coal", "count": 16}],
    ("t00", "terminal"): [{"item": "gtna:nexus_structure_terminal"}],
    ("t01", "dimensao"): [{"item": "modernspace:personal_space_portal", "count": 2}],
}


def tsv(path: Path) -> dict[tuple[str, str], list[str]]:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            chapter, key, *rest = line.split("\t")
            rows[(chapter, key)] = rest
    return rows


def join(names: list[str], lang: str) -> str:
    if lang == "zh":
        return "、".join(names)
    word = {"en": "and", "pt": "e"}[lang]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" {word} " + names[-1]


def toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(float(value)) if isinstance(value, float) else str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {toml_value(v)}" for k, v in value.items()) + " }"
    raise TypeError(value)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drafts", type=Path, default=DRAFTS, help="folder with the tipo0_* draft folders")
    args = ap.parse_args()

    titles = tsv(DATA / "type0_titles.tsv")
    tips = tsv(DATA / "type0_tips.tsv")
    items = set((REGISTRY / "items.txt").read_text(encoding="utf-8").split())
    fluids = set((REGISTRY / "fluids.txt").read_text(encoding="utf-8").split())

    drafts = {}
    for prefix, rel, file, en, zh in CHAPTERS:
        data = runpy.run_path(str(args.drafts / rel))
        drafts[prefix] = {"file": file, "title": (en, data["TITLE"].replace(" · ", " · "), zh), "Q": data["Q"]}

    # quest index: (prefix, id) -> record
    quests: dict[tuple[str, str], dict] = {}
    for prefix, d in drafts.items():
        for i, (qid, label, role, size, x, y, deps, item) in enumerate(d["Q"]):
            key = "entry" if i == 0 else "exit" if role == "exit" else qid
            en, zh = titles[(prefix, qid)]
            parsed = []
            for dep in deps:
                hidden = dep.startswith("~")
                name = dep.lstrip("~").strip()
                target = tuple(name.split(":", 1)) if re.match(r"t\d\d:", name) else (prefix, name)
                parsed.append((target, hidden))
            quests[(prefix, qid)] = {"prefix": prefix, "id": qid, "key": key, "role": role, "size": size, "x": x,
                                     "y": y, "deps": parsed, "items": [ID_ALIAS.get(i, i) for i in item.split("|")],
                                     "title": (en, label, zh), "first": i == 0}
    for q in quests.values():
        for target, _ in q["deps"]:
            if target not in quests:
                raise SystemExit(f"{q['prefix']}:{q['id']}: unknown dependency {target}")

    # EN: drop a dependency another dependency already implies, as questgen does, so the line flags below match
    #     the dependencies FTB Quests ends up with.
    # PT: tira a dependência que outra já implica, como o questgen faz, para as marcas de linha abaixo baterem
    #     com as dependências que ficam no FTB Quests.
    # ZH: 与 questgen 相同，删除已被其他依赖隐含的依赖，使下面的连线标记与 FTB Quests 中最终的依赖一致。
    memo: dict = {}

    def ancestors(k):
        if k not in memo:
            memo[k] = set()
            for t, _ in quests[k]["deps"]:
                memo[k] |= {t} | ancestors(t)
        return memo[k]

    for q in quests.values():
        targets = [t for t, _ in q["deps"]]
        if len(targets) > 1:
            kept = [(t, h) for t, h in q["deps"] if not any(t in ancestors(o) for o in targets if o != t)]
            dropped_visible = [t for t, h in q["deps"] if not h and (t, h) not in kept]
            # a kept "~" dependency that now stands for a dropped visible one draws its line
            q["deps"] = [(t, h and not any(d in ancestors(t) for d in dropped_visible)) for t, h in kept]

    # Lines: FTB Quests hides lines per quest, not per dependency. A quest whose drawn-chapter dependencies are all
    # "~" hides its incoming lines; a quest whose dependents all reach it with "~" hides its outgoing lines; a "~"
    # line that fits neither stays drawn and is counted.
    local = lambda q: [(t, h) for t, h in q["deps"] if t[0] == q["prefix"]]
    out_edges: dict = {}
    for k, q in quests.items():
        for t, h in local(q):
            out_edges.setdefault(t, []).append(h)
    drawn_anyway = []
    for k, q in quests.items():
        deps = local(q)
        q["hide_lines"] = bool(deps) and all(h for _, h in deps)
        q["hide_dependents"] = bool(out_edges.get(k)) and all(out_edges[k])
    for k, q in quests.items():
        if q["hide_lines"]:
            continue
        for t, h in local(q):
            if h and not quests[t]["hide_dependents"]:
                drawn_anyway.append(f"{q['prefix']}:{t[1]} -> {q['id']}")

    children: dict = {}
    for k, q in quests.items():
        for t, _ in q["deps"]:
            children.setdefault(t, []).append(k)

    lang = {"pt": {}, "zh": {}}

    def text(en: str, pt: str, zh: str) -> str:
        lang["pt"][en], lang["zh"][en] = pt, zh
        return en

    group = text("Type 0", "Tipo 0", "0型")
    next_title = {}
    for i, (prefix, *_rest) in enumerate(CHAPTERS):
        if i + 1 < len(CHAPTERS):
            next_title[prefix] = drafts[CHAPTERS[i + 1][0]]["title"]
    substituted, special = [], []
    for prefix, d in drafts.items():
        en, pt, zh = d["title"]
        text(en, pt, zh)
        lines = ["# Generated by tools/draft_to_questsrc.py from the approved Type 0 draft "
                 f"{prefix} (GTIA-D-421: development beta). Rerun it instead of editing by hand.", "",
                 "[chapter]", f"title = {toml_value(en)}", f"icon = {toml_value(next(q for q in quests.values() if q['prefix'] == prefix and q['first'])['items'][0])}", ""]
        body = []
        for qid, *_ in d["Q"]:
            q = quests[(prefix, qid)]
            role = "entry" if q["first"] else q["role"]
            # tasks
            tasks, missing = [], []
            if (prefix, qid) in SPECIAL_TASKS:
                tasks = SPECIAL_TASKS[(prefix, qid)]
                special.append(f"{prefix}:{qid}")
            elif q["role"] not in ("tip", "guide"):
                for item in q["items"]:
                    if item not in items:
                        missing.append(item)
                        if item in STAND_IN_TASK:
                            tasks.append({"item": STAND_IN[item]})
                        continue
                    fluid = item.removesuffix("_bucket")
                    if item.endswith("_bucket") and fluid in fluids:
                        tasks.append({"fluid": fluid, "amount": 1000})
                    else:
                        tasks.append({"item": item})
            else:
                missing = [i for i in q["items"] if i not in items]
            icon = q["items"][0]
            if icon not in items:
                icon = STAND_IN.get(icon, "minecraft:barrier")
            for item in missing:
                substituted.append(f"{prefix}:{qid}: {item} -> {STAND_IN.get(item, '?')}"
                                   + (" (icon of a tip)" if q["role"] in ("tip", "guide") else " (task)"
                                      if item in STAND_IN_TASK else " (icon, checkmark)" if not tasks else " (icon)"))
            # text
            sub = SUBTITLE[role]
            subtitle = text(*sub)
            en_t, pt_t, zh_t = q["title"]
            text(en_t, pt_t, zh_t)
            kids = [quests[c] for c in children.get((prefix, qid), [])]
            names = [(c["title"][0], c["title"][1], c["title"][2]) for c in kids]
            paragraphs = []
            if (prefix, qid) in tips:
                paragraphs.append(text(*tips[(prefix, qid)]))
            elif q["role"] == "bridge":
                if pt_t.startswith("Química"):
                    paragraphs.append(text(
                        "Chemistry bridge: make the product now; its full line gets a chapter of its own later.",
                        "Ponte de química: faça o produto agora; a linha completa ganha um capítulo próprio depois.",
                        "化学桥接：现在先制作产物；完整产线以后会有独立章节。"))
                elif pt_t.startswith("Tipo I"):
                    paragraphs.append(text("Type I begins with the landing on Mars.",
                                           "O Tipo I começa com o pouso em Marte.", "I 型从登陆火星开始。"))
                else:
                    n = pt_t.split(" · ")[0]
                    paragraphs.append(text(f"Continues in chapter {n.replace(',', '.')}.",
                                           f"Continua no capítulo {n}.", f"在 {n.replace(',', '.')} 章继续。"))
            if role == "exit" and prefix in next_title:
                nt = next_title[prefix]
                paragraphs.append(text(f"Finishes this chapter and opens {nt[0]}.",
                                       f"Fecha este capítulo e abre o {nt[1]}.", f"完成本章并开启 {nt[2]}。"))
            if names and q["role"] not in ("tip",):
                shown = names[:6]
                more = len(names) - len(shown)
                tail = ({"en": f" and {more} more", "pt": f" e mais {more}", "zh": f"等 {len(names)} 项"}
                        if more else {"en": "", "pt": "", "zh": ""})
                if more:
                    paragraphs.append(text(
                        f"Needed for: {', '.join(n[0] for n in shown)}{tail['en']}.",
                        f"Serve para: {', '.join(n[1] for n in shown)}{tail['pt']}.",
                        f"用于：{'、'.join(n[2] for n in shown)}{tail['zh']}。"))
                else:
                    paragraphs.append(text(
                        f"Needed for: {join([n[0] for n in shown], 'en')}.",
                        f"Serve para: {join([n[1] for n in shown], 'pt')}.",
                        f"用于：{join([n[2] for n in shown], 'zh')}。"))
            elif not paragraphs:
                if role in ("machine", "multi"):
                    paragraphs.append(text("An optional machine of this stage: nothing in the book waits for it.",
                                           "Máquina opcional desta etapa: nada no livro espera por ela.",
                                           "本阶段的可选机器：书中没有任务依赖它。"))
                else:
                    paragraphs.append(text("Make it; later stages use it.", "Faça; etapas seguintes usam.",
                                           "制作它，后续阶段会用到。"))
            if missing and not (prefix, qid) in tips and q["role"] not in ("tip", "guide"):
                paragraphs.append(text(
                    "Beta: this item is not in the pack yet, so the quest is a checkmark for now."
                    if not tasks else "Beta: a stand-in item is asked for until the real one is in the pack.",
                    "Beta: este item ainda não existe no pack, então a quest é um checkmark por enquanto."
                    if not tasks else "Beta: um item substituto é pedido até o item real entrar no pack.",
                    "测试版：该物品尚未加入整合包，暂时改为勾选任务。"
                    if not tasks else "测试版：在正式物品加入前，暂用替代物品。"))
            fields = {}
            if role == "entry":
                fields["title"] = en_t
                fields["requires"] = [ref(quests, t, prefix) for t, _ in q["deps"]]
            elif role == "exit":
                fields["title"] = en_t
                fields["deps"] = [ref(quests, t, prefix) for t, _ in q["deps"]]
            else:
                fields["key"] = qid
                fields["title"] = en_t
                fields["role"] = ROLE.get(q["role"], "side")
                fields["deps"] = [ref(quests, t, prefix) for t, _ in q["deps"]]
            fields["subtitle"] = subtitle
            fields["icon"] = icon
            fields["x"] = float(q["x"])
            fields["y"] = float(q["y"])
            fields["shape"] = SHAPES[q["role"]]
            fields["size"] = float(q["size"])
            if tasks:
                fields["task"] = tasks
            elif role in ("entry", "exit"):
                fields["task"] = [{"checkmark": "Read and continue"}]
            if q["hide_lines"]:
                fields["hide_lines"] = True
            if q["hide_dependents"]:
                fields["hide_dependents"] = True
            if (prefix, qid) in REWARDS:
                fields["reward"] = REWARDS[(prefix, qid)]
            fields["text"] = "\n\n".join(paragraphs)
            header = "[entry]" if role == "entry" else "[exit]" if role == "exit" else "[[quest]]"
            block = [header] + [f"{k} = {toml_value(v)}" for k, v in fields.items() if k != "text"]
            block.append('text = """\n' + fields["text"].replace("\\", "\\\\") + '\n"""')
            body.append("\n".join(block))
        (SRC / f"{d['file']}.toml").write_text("\n".join(lines) + "\n" + "\n\n".join(body) + "\n", encoding="utf-8")
        print(f"wrote quests-src/{d['file']}.toml ({len(d['Q'])} quests)")

    for code, name in (("pt", "pt_br"), ("zh", "zh_cn")):
        path = SRC / "lang" / f"{name}.json"
        table = json.loads(path.read_text(encoding="utf-8"))
        added, kept = 0, []
        for en, tr in lang[code].items():
            if en not in table or (table[en] == en and tr != en):  # missing, or left in English before
                table[en] = tr
                added += 1
            elif table[en] != tr:
                kept.append(f"{en!r}: kept {table[en]!r}, draft {tr!r}")
        path.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"lang/{name}.json: {added} added, {len(kept)} existing translations kept")
        for line in kept:
            print("  kept", line)
    print(f"{len(substituted)} id(s) not in the registry:")
    for line in substituted:
        print("  " + line)
    print(f"{len(drawn_anyway)} hidden (~) line(s) FTB Quests cannot hide alone, drawn:")
    for line in drawn_anyway:
        print("  " + line)
    return 0


def ref(quests, target, prefix) -> str:
    q = quests[target]
    file = next(f for p, _r, f, *_ in CHAPTERS if p == target[0])
    return q["key"] if target[0] == prefix else f"{file}:{q['key']}"


if __name__ == "__main__":
    raise SystemExit(main())
