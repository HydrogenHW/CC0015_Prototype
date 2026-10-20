"""Build the core TCM glossary and fact-check every English rendering
against the WHO ISTTM (2007) full text.

The PDF's Chinese column is unrecoverable, so this script works the other
way round: we propose the Chinese->English pairs, then verify that each
English rendering actually appears in the WHO standard's English text.
A miss is not automatically an error (WHO may phrase it differently inside
a definition), but it flags exactly what a human needs to review.
"""
import json, re, sys, unicodedata

# (zh, en, category, source)  source: "who" = believed verbatim from WHO,
#                                     "conv" = conventional literature rendering
TERMS = [
    # ---------- 基础理论 ----------
    ("阴阳", "yin-yang", "theory", "who"),
    ("阴", "yin", "theory", "who"),
    ("阳", "yang", "theory", "who"),
    ("五行", "five phases", "theory", "who"),
    ("木", "wood", "theory", "who"),
    ("火（五行）", "fire", "theory", "who"),
    ("土", "earth", "theory", "who"),
    ("金", "metal", "theory", "who"),
    ("水（五行）", "water", "theory", "who"),
    ("相生", "engendering", "theory", "who"),
    ("相克", "restraining", "theory", "who"),
    ("相乘", "overacting", "theory", "who"),
    ("相侮", "counteracting", "theory", "who"),
    ("阴阳互根", "mutual rooting of yin and yang", "theory", "who"),
    ("阴阳转化", "yin-yang conversion", "theory", "who"),
    ("阴阳消长", "waxing and waning of yin and yang", "theory", "who"),
    ("阴阳失衡", "yin-yang imbalance", "theory", "who"),
    ("五行学说", "five phase theory", "theory", "who"),

    # ---------- 精气血津液神 ----------
    ("精", "essence", "substance", "who"),
    ("气", "qi", "substance", "who"),
    ("血", "blood", "substance", "who"),
    ("津液", "body fluid", "substance", "who"),
    ("神", "spirit", "substance", "who"),
    ("元气", "original qi", "substance", "who"),
    ("宗气", "pectoral qi", "substance", "who"),
    ("营气", "nutrient qi", "substance", "who"),
    ("卫气", "defensive qi", "substance", "who"),
    ("中气", "middle qi", "substance", "who"),
    ("正气", "healthy qi", "substance", "who"),
    ("邪气", "pathogenic qi", "substance", "who"),
    ("气血两虚", "qi and blood deficiency", "pattern", "who"),
    ("气虚", "qi deficiency", "pattern", "who"),
    ("气滞", "qi stagnation", "pathology", "who"),
    ("气逆", "qi counterflow", "pathology", "who"),
    ("气陷", "qi sinking", "pathology", "who"),
    ("气脱", "qi collapse", "pathology", "who"),
    ("血虚", "blood deficiency", "pattern", "who"),
    ("血瘀", "blood stasis", "pathology", "who"),
    ("血热", "blood heat", "pathology", "who"),
    ("血寒", "blood cold", "pathology", "who"),
    ("痰", "phlegm", "pathology", "who"),
    ("饮", "retained fluid", "pathology", "who"),
    ("水湿", "water-dampness", "pathology", "who"),
    ("津亏", "fluid depletion", "pathology", "conv"),
    ("痰湿", "phlegm-dampness", "pathology", "conv"),
    ("痰热", "phlegm-heat", "pathology", "conv"),
    ("痰浊", "phlegm turbidity", "pathology", "conv"),

    # ---------- 脏腑 ----------
    ("五脏", "five zang-organs", "organ", "who"),
    ("六腑", "six fu-organs", "organ", "who"),
    ("心", "heart", "organ", "who"),
    ("肝", "liver", "organ", "who"),
    ("脾", "spleen", "organ", "who"),
    ("肺", "lung", "organ", "who"),
    ("肾", "kidney", "organ", "who"),
    ("心包", "pericardium", "organ", "who"),
    ("胆", "gallbladder", "organ", "who"),
    ("胃", "stomach", "organ", "who"),
    ("小肠", "small intestine", "organ", "who"),
    ("大肠", "large intestine", "organ", "who"),
    ("膀胱", "bladder", "organ", "who"),
    ("三焦", "triple energizer", "organ", "who"),
    ("奇恒之腑", "extraordinary fu-organs", "organ", "who"),
    ("脑", "brain", "organ", "who"),
    ("髓", "marrow", "organ", "who"),
    ("骨", "bone", "organ", "who"),
    ("脉", "vessel", "organ", "who"),
    ("女子胞", "uterus", "organ", "who"),
    ("脾胃", "spleen and stomach", "organ", "conv"),
    ("心主神明", "heart governs mental activities", "organ", "conv"),
    ("肝主疏泄", "liver governs free flow", "organ", "conv"),
    ("脾主运化", "spleen governs transportation and transformation", "organ", "conv"),
    ("肝藏血", "liver stores blood", "organ", "conv"),
    ("肾藏精", "kidney stores essence", "organ", "conv"),
    ("脾统血", "spleen controls blood", "organ", "conv"),
    ("心主血脉", "heart governs blood and vessels", "organ", "conv"),
    ("肝肾同源", "liver and kidney share the same source", "organ", "conv"),
    ("心肾相交", "interaction between heart and kidney", "organ", "conv"),

    # ---------- 经络 ----------
    ("经络", "meridian and collateral", "meridian", "who"),
    ("经脉", "meridian", "meridian", "who"),
    ("络脉", "collateral", "meridian", "who"),
    ("十二正经", "twelve regular meridians", "meridian", "who"),
    ("奇经八脉", "eight extra meridians", "meridian", "who"),
    ("任脉", "Conception Vessel", "meridian", "who"),
    ("督脉", "Governing Vessel", "meridian", "who"),
    ("冲脉", "Penetrating Vessel", "meridian", "who"),
    ("带脉", "Girdling Vessel", "meridian", "who"),
    ("手太阴肺经", "Hand-Taiyin Lung Meridian", "meridian", "who"),
    ("手阳明大肠经", "Hand-Yangming Large Intestine Meridian", "meridian", "who"),
    ("足阳明胃经", "Foot-Yangming Stomach Meridian", "meridian", "who"),
    ("足太阴脾经", "Foot-Taiyin Spleen Meridian", "meridian", "who"),
    ("手少阴心经", "Hand-Shaoyin Heart Meridian", "meridian", "who"),
    ("手太阳小肠经", "Hand-Taiyang Small Intestine Meridian", "meridian", "who"),
    ("足太阳膀胱经", "Foot-Taiyang Bladder Meridian", "meridian", "who"),
    ("足少阴肾经", "Foot-Shaoyin Kidney Meridian", "meridian", "who"),
    ("手厥阴心包经", "Hand-Jueyin Pericardium Meridian", "meridian", "who"),
    ("手少阳三焦经", "Hand-Shaoyang Sanjiao Meridian", "meridian", "who"),
    ("足少阳胆经", "Foot-Shaoyang Gallbladder Meridian", "meridian", "who"),
    ("足厥阴肝经", "Foot-Jueyin Liver Meridian", "meridian", "who"),
    ("腧穴", "acupoint", "meridian", "who"),

    # ---------- 病因病机 ----------
    ("六淫", "six excesses", "pathology", "who"),
    ("风", "wind", "pathology", "who"),
    ("寒", "cold", "pathology", "who"),
    ("暑", "summerheat", "pathology", "who"),
    ("湿", "dampness", "pathology", "who"),
    ("燥", "dryness", "pathology", "who"),
    ("热", "heat", "pathology", "who"),
    ("七情", "seven emotions", "pathology", "who"),
    ("喜", "joy", "pathology", "who"),
    ("怒", "anger", "pathology", "who"),
    ("忧", "anxiety", "pathology", "who"),
    ("思", "thought", "pathology", "who"),
    ("悲", "sorrow", "pathology", "who"),
    ("恐", "fear", "pathology", "who"),
    ("惊", "fright", "pathology", "who"),
    ("内伤", "internal damage", "pathology", "who"),
    ("疠气", "pestilential qi", "pathology", "who"),
    ("病机", "pathogenesis", "pathology", "who"),
    ("传变", "transmission and transformation", "pathology", "conv"),
    ("正邪相争", "struggle between healthy qi and pathogenic qi", "pathology", "conv"),
    ("虚实夹杂", "deficiency-excess complex", "pathology", "conv"),

    # ---------- 四诊 ----------
    ("四诊", "four diagnostic methods", "diagnosis", "who"),
    ("望诊", "inspection", "diagnosis", "who"),
    ("闻诊", "listening and smelling", "diagnosis", "who"),
    ("问诊", "inquiry", "diagnosis", "who"),
    ("切诊", "palpation", "diagnosis", "who"),
    ("舌诊", "tongue diagnosis", "diagnosis", "who"),
    ("舌质", "tongue body", "diagnosis", "who"),
    ("舌苔", "tongue coating", "diagnosis", "who"),
    ("脉诊", "pulse diagnosis", "diagnosis", "who"),
    ("脉象", "pulse image", "diagnosis", "who"),
    ("浮脉", "floating pulse", "diagnosis", "who"),
    ("沉脉", "deep pulse", "diagnosis", "who"),
    ("迟脉", "slow pulse", "diagnosis", "who"),
    ("数脉", "rapid pulse", "diagnosis", "who"),
    ("虚脉", "vacuous pulse", "diagnosis", "who"),
    ("实脉", "replete pulse", "diagnosis", "who"),
    ("滑脉", "slippery pulse", "diagnosis", "who"),
    ("涩脉", "choppy pulse", "diagnosis", "who"),
    ("弦脉", "wiry pulse", "diagnosis", "who"),
    ("舌红", "red tongue", "diagnosis", "conv"),
    ("舌淡", "pale tongue", "diagnosis", "conv"),
    ("苔黄", "yellow coating", "diagnosis", "conv"),
    ("苔白", "white coating", "diagnosis", "conv"),
    ("苔腻", "greasy coating", "diagnosis", "conv"),

    # ---------- 八纲 ----------
    ("八纲", "eight principles", "diagnosis", "who"),
    ("表", "exterior", "diagnosis", "who"),
    ("里", "interior", "diagnosis", "who"),
    ("虚", "deficiency", "diagnosis", "who"),
    ("实", "excess", "diagnosis", "who"),
    ("表证", "exterior pattern", "diagnosis", "who"),
    ("里证", "interior pattern", "diagnosis", "who"),
    ("寒证", "cold pattern", "diagnosis", "who"),
    ("热证", "heat pattern", "diagnosis", "who"),
    ("虚证", "deficiency pattern", "diagnosis", "who"),
    ("实证", "excess pattern", "diagnosis", "who"),
    ("半表半里", "half-exterior half-interior", "diagnosis", "who"),
    ("寒热错杂", "cold-heat complex", "diagnosis", "conv"),
    ("辨证论治", "pattern identification and treatment", "diagnosis", "who"),
    ("证候", "pattern", "diagnosis", "who"),
    ("六经辨证", "six-meridian pattern identification", "diagnosis", "conv"),
    ("三焦辨证", "sanjiao pattern identification", "diagnosis", "conv"),
    ("卫气营血辨证", "wei-qi-ying-xue pattern identification", "diagnosis", "conv"),

    # ---------- 常见证型 ----------
    ("肝气郁结", "liver qi stagnation", "pattern", "conv"),
    ("肝火上炎", "liver fire flaming upward", "pattern", "conv"),
    ("肝阳上亢", "liver yang hyperactivity", "pattern", "conv"),
    ("肝血虚", "liver blood deficiency", "pattern", "conv"),
    ("肝阴虚", "liver yin deficiency", "pattern", "conv"),
    ("脾气虚", "spleen qi deficiency", "pattern", "conv"),
    ("脾阳虚", "spleen yang deficiency", "pattern", "conv"),
    ("脾虚湿困", "spleen deficiency with dampness retention", "pattern", "conv"),
    ("心气虚", "heart qi deficiency", "pattern", "conv"),
    ("心阳虚", "heart yang deficiency", "pattern", "conv"),
    ("心血虚", "heart blood deficiency", "pattern", "conv"),
    ("心火亢盛", "heart fire hyperactivity", "pattern", "conv"),
    ("心血瘀阻", "heart blood stasis", "pattern", "conv"),
    ("肺气虚", "lung qi deficiency", "pattern", "conv"),
    ("肺阴虚", "lung yin deficiency", "pattern", "conv"),
    ("风寒犯肺", "wind-cold invading lung", "pattern", "conv"),
    ("风热犯肺", "wind-heat invading lung", "pattern", "conv"),
    ("肾阳虚", "kidney yang deficiency", "pattern", "conv"),
    ("肾阴虚", "kidney yin deficiency", "pattern", "conv"),
    ("肾气不固", "kidney qi insecurity", "pattern", "conv"),
    ("肾精不足", "kidney essence insufficiency", "pattern", "conv"),
    ("胃阴虚", "stomach yin deficiency", "pattern", "conv"),
    ("胃火", "stomach fire", "pattern", "conv"),
    ("痰浊阻肺", "phlegm turbidity obstructing lung", "pattern", "conv"),
    ("痰蒙心窍", "phlegm clouding heart orifice", "pattern", "conv"),
    ("膀胱湿热", "bladder damp-heat", "pattern", "conv"),
    ("太阳伤寒", "Taiyang cold damage", "pattern", "conv"),
    ("少阳证", "Shaoyang pattern", "pattern", "conv"),
    ("阳明证", "Yangming pattern", "pattern", "conv"),
    ("卫分证", "Wei-level pattern", "pattern", "conv"),
    ("气分证", "Qi-level pattern", "pattern", "conv"),
    ("营分证", "Ying-level pattern", "pattern", "conv"),
    ("血分证", "Xue-level pattern", "pattern", "conv"),
    ("上热下寒", "upper heat and lower cold", "pattern", "conv"),
    ("心脾两虚", "heart and spleen deficiency", "pattern", "conv"),
    ("肝肾阴虚", "liver and kidney yin deficiency", "pattern", "conv"),
    ("阴虚火旺", "yin deficiency with hyperactive fire", "pattern", "conv"),
    ("阳虚水泛", "yang deficiency with water diffusion", "pattern", "conv"),

    # ---------- 治法 ----------
    ("治则", "treatment principle", "treatment", "conv"),
    ("补", "tonify", "treatment", "who"),
    ("泻", "purge", "treatment", "who"),
    ("温", "warm", "treatment", "who"),
    ("清", "clear heat", "treatment", "who"),
    ("汗法", "diaphoresis", "treatment", "who"),
    ("吐法", "emesis", "treatment", "who"),
    ("下法", "purgation", "treatment", "who"),
    ("和法", "harmonizing method", "treatment", "conv"),
    ("消法", "resolution method", "treatment", "conv"),
    ("益气", "replenish qi", "treatment", "conv"),
    ("养血", "nourish blood", "treatment", "conv"),
    ("滋阴", "nourish yin", "treatment", "conv"),
    ("温阳", "warm yang", "treatment", "conv"),
    ("活血化瘀", "invigorate blood and resolve stasis", "treatment", "conv"),
    ("行气", "move qi", "treatment", "conv"),
    ("化痰", "resolve phlegm", "treatment", "conv"),
    ("祛湿", "eliminate dampness", "treatment", "conv"),
    ("疏肝", "soothe liver", "treatment", "conv"),
    ("健脾", "strengthen spleen", "treatment", "conv"),
    ("补肾", "tonify kidney", "treatment", "conv"),
    ("清热解毒", "clear heat and resolve toxin", "treatment", "conv"),
    ("针灸", "acupuncture and moxibustion", "treatment", "who"),
    ("针刺", "acupuncture", "treatment", "who"),
    ("艾灸", "moxibustion", "treatment", "who"),
    ("拔罐", "cupping", "treatment", "conv"),
    ("推拿", "tuina", "treatment", "conv"),

    # ---------- 方剂 ----------
    ("四君子汤", "Four Gentlemen Decoction", "formula", "conv"),
    ("四物汤", "Four Substances Decoction", "formula", "conv"),
    ("八珍汤", "Eight Treasure Decoction", "formula", "conv"),
    ("六味地黄丸", "Six-Ingredient Rehmannia Pill", "formula", "conv"),
    ("桂枝汤", "Cinnamon Twig Decoction", "formula", "conv"),
    ("麻黄汤", "Ephedra Decoction", "formula", "conv"),
    ("小柴胡汤", "Minor Bupleurum Decoction", "formula", "conv"),
    ("逍遥散", "Free Wanderer Powder", "formula", "conv"),
    ("补中益气汤", "Decoction for Tonifying the Middle and Benefiting Qi", "formula", "conv"),
    ("归脾汤", "Decoction for Restoring Spleen", "formula", "conv"),
    ("温胆汤", "Decoction for Warming Gallbladder", "formula", "conv"),
    ("玉屏风散", "Jade Windscreen Powder", "formula", "conv"),
    ("银翘散", "Lonicera and Forsythia Powder", "formula", "conv"),
    ("血府逐瘀汤", "Decoction for Removing Blood Stasis in the Blood Mansion", "formula", "conv"),
    ("天王补心丹", "Celestial Emperor Heart-Supplementing Elixir", "formula", "conv"),

    # ---------- 常用穴位 ----------
    ("合谷", "Hegu (LI4)", "acupoint", "who"),
    ("足三里", "Zusanli (ST36)", "acupoint", "who"),
    ("太冲", "Taichong (LR3)", "acupoint", "who"),
    ("三阴交", "Sanyinjiao (SP6)", "acupoint", "who"),
    ("内关", "Neiguan (PC6)", "acupoint", "who"),
    ("百会", "Baihui (GV20)", "acupoint", "who"),
    ("关元", "Guanyuan (CV4)", "acupoint", "who"),
    ("气海", "Qihai (CV6)", "acupoint", "who"),
    ("神门", "Shenmen (HT7)", "acupoint", "who"),
    ("曲池", "Quchi (LI11)", "acupoint", "who"),
    ("阳陵泉", "Yanglingquan (GB34)", "acupoint", "who"),
    ("阴陵泉", "Yinlingquan (SP9)", "acupoint", "who"),
    ("太溪", "Taixi (KI3)", "acupoint", "who"),
    ("风池", "Fengchi (GB20)", "acupoint", "who"),
    ("中脘", "Zhongwan (CV12)", "acupoint", "who"),
    ("血海", "Xuehai (SP10)", "acupoint", "who"),
    ("尺泽", "Chize (LU5)", "acupoint", "who"),

    # ---------- 一般用语 ----------
    ("中医", "traditional Chinese medicine", "general", "who"),
    ("中药", "Chinese materia medica", "general", "who"),
    ("本草", "materia medica", "general", "who"),
    ("方剂", "formula", "general", "who"),
    ("四气", "four natures", "general", "conv"),
    ("五味", "five flavors", "general", "who"),
    ("归经", "channel tropism", "general", "conv"),
    ("君臣佐使", "sovereign, minister, assistant and courier", "general", "conv"),
]


def norm(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"\s+", " ", s).strip()


def main():
    # WHO full text as one searchable blob (English column only survives).
    raw = open("data/raw/who_2007.txt", encoding="utf-8", errors="replace").read()
    blob = norm(raw.replace("\u00ad", "").replace("- ", "-"))
    # also a de-hyphenated variant, for terms broken across lines
    blob_nh = norm(raw.replace("-\n", "").replace("\n", " "))

    out, miss = [], []
    for zh, en, cat, src in TERMS:
        e = norm(en)
        hit = e in blob or e in blob_nh
        # for "X (LI4)" strip the parenthetical when checking
        if not hit:
            base = re.sub(r"\s*\(.*?\)\s*$", "", en)
            hit = norm(base) in blob
        out.append({"zh": zh, "en": en, "category": cat,
                    "source": src, "who_hit": hit})
        if not hit:
            miss.append((zh, en))

    json.dump(out, open("data/glossary.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    hit_n = sum(1 for x in out if x["who_hit"])
    print(f"[total] {len(out)} terms")
    print(f"[who-hit] {hit_n} ({hit_n/len(out)*100:.1f}%)")
    print(f"[miss] {len(miss)} —— 需要人工确认：")
    for zh, en in miss:
        print(f"    {zh:12} {en}")


if __name__ == "__main__":
    main()
