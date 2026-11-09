"""Seed archives for the Master Vision style library.

Each archive is original research material describing a visual language, not
a fixed parameter table and not a reproduction of copyrighted photographs.
The stage 5 planner consumes the archive as decision context; the envelope
only bounds what the stage 4 engine may realise. Seeding is idempotent:
existing profiles (including user edits and newer versions) are never
overwritten.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.photographer import DirectionConstraint, StyleEnvelope
from app.models.style_profile import (
    StyleColorTraits,
    StyleCompositionTraits,
    StyleKind,
    StyleLightTraits,
    StyleProfile,
    StyleSceneFit,
    StyleSource,
    StyleTextureTraits,
)
from app.repositories.style_repo import SqliteStyleProfileRepository

_LICENSE = "风格研究原创整理；不复制或再分发受版权保护的原作。"


def _source(title: str) -> StyleSource:
    return StyleSource(title=title, url=None, license=_LICENSE)


def _profile(**data: Any) -> StyleProfile:
    # Keyword construction with runtime validation: the archive content uses
    # JSON-friendly lists, which pydantic coerces to the frozen tuple fields.
    return StyleProfile.model_validate(data)


def _scene_fit(**data: Any) -> StyleSceneFit:
    return StyleSceneFit.model_validate(data)


SAUL_LEITER = _profile(
    id="saul_leiter",
    kind=StyleKind.MASTER,
    name="Saul Leiter 色彩街头",
    description="以克制色彩、层叠反射与遮挡关系把纽约街头拍成抽象绘画的彩色先驱。",
    philosophy=(
        "把街头当作色彩与形状的画布：透过雨窗、雨伞、人群与玻璃反射观察城市，"
        "让日常场景呈现绘画般的抽象层次，色彩服务于情绪而非记录。"
    ),
    color=StyleColorTraits(
        tendency="低饱和暖调为主，偶以小面积高饱和红/黄作为视觉锚点",
        relationships="邻近色和谐，反射层之间形成冷暖交错",
        saturation="整体偏低，强调色彩面积对比而非浓度",
    ),
    light=StyleLightTraits(
        contrast="中低对比，柔和过渡",
        shadows="保留细节的灰暗部，不压死黑",
        highlights="抑制刺眼亮部，容忍轻微雾化",
        expression="阴天、雨天与橱窗反射形成的漫射光",
    ),
    composition=StyleCompositionTraits(
        space="多层前景遮挡制造压缩的空间纵深",
        geometry="碎片化几何，非对称平衡",
        negative_space="以遮挡物与暗部形成呼吸空间",
        subject_relation="主体常被部分遮蔽，若隐若现",
    ),
    texture=StyleTextureTraits(
        grain="细腻胶片颗粒",
        sharpness="偏软，不追求极致锐利",
        detail="保留反射与雨痕的中间调细节",
    ),
    scene_fit=_scene_fit(
        suitable=["street", "architecture", "night"],
        suitable_notes="有玻璃、雨伞、人群遮挡与反射层次的城市街头",
        unsuitable_notes="光线直白、缺少前景层次与反射元素的开阔场景",
    ),
    post_strategy=(
        "可通过降低整体饱和、暖调偏移、柔化对比、压高光与轻暗角实现；"
        "用已有蒙版对背景做轻度去饱和以突出小面积色彩锚点。"
    ),
    capture_techniques=(
        "无法凭空创造雨窗反射、前景遮挡物或压缩透视；这些依赖拍摄时的"
        "机位、天气与长焦选择，后期只能强化已有层次。"
    ),
    constraints=[
        DirectionConstraint.KEEP_AMBIENT_COLOR,
        DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
        DirectionConstraint.AVOID_EXTREME_SATURATION,
    ],
    preserve_notes="保留现场漫射光氛围与反射层的色彩关系，不把画面调成高对比硬光。",
    sources=[_source("Saul Leiter: Early Color (Steidl, 2006) 视觉语言研究")],
    engine_style="street",
    envelope=StyleEnvelope(
        exposure_ev=0.8,
        contrast=20,
        highlights=25,
        shadows=20,
        whites=15,
        blacks=15,
        temperature=15,
        tint=10,
        saturation=25,
        vibrance=20,
        clarity=15,
        vignette=20,
        grain=15,
    ),
    default_strength=0.55,
)

FAN_HO = _profile(
    id="fan_ho",
    kind=StyleKind.MASTER,
    name="Fan Ho 光影几何",
    description="以强烈方向性光线、几何阴影与孤身人物构建街头戏剧的黑白大师。",
    philosophy=(
        "光是主角：在街道与建筑间等待光束切开空间的瞬间，让人物走进光区，"
        "用明暗交界和几何分割讲述寂静的城市诗意。"
    ),
    color=StyleColorTraits(
        tendency="以黑白影调为核心，色彩表达极度克制",
        relationships="明暗关系取代色彩关系成为结构手段",
        saturation="去饱和至单色，保留细腻灰阶",
    ),
    light=StyleLightTraits(
        contrast="高对比，明暗交界清晰",
        shadows="大面积深阴影构成几何形状",
        highlights="集中受光区，保护光束内细节",
        expression="低角度直射光形成的长影与光带",
    ),
    composition=StyleCompositionTraits(
        space="前景暗部框景，中景光区承载主体",
        geometry="强烈的对角线、三角与重复线条",
        negative_space="暗部留白衬托孤身人物",
        subject_relation="人物置于光区，与背景形成明暗分离",
    ),
    texture=StyleTextureTraits(
        grain="经典银盐颗粒，细腻均匀",
        sharpness="适中偏锐，突出结构线条",
        detail="亮部与暗部两端都保留层次",
    ),
    scene_fit=_scene_fit(
        suitable=["street", "architecture"],
        suitable_notes="存在明显方向性光线、建筑结构与空间层次的街头",
        unsuitable_notes="光线平坦、缺少几何结构与明暗分割的照片",
    ),
    post_strategy=(
        "可转黑白并用 S 曲线拉开影调，局部曝光突出已有光区、压暗干扰背景，"
        "适度清晰度强化建筑线条；明暗结构必须来自照片本身。"
    ),
    capture_techniques=(
        "不能凭空创造真实光源、光束方向、人物姿态或拍摄瞬间；"
        "平光照片无法通过调色伪造出戏剧性光影结构。"
    ),
    constraints=[
        DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
        DirectionConstraint.PRESERVE_SHADOW_DETAIL,
        DirectionConstraint.MAINTAIN_NEUTRALITY,
    ],
    preserve_notes="不破坏人物身份与现场光线方向；黑白转换保持中性灰阶，不偏色。",
    sources=[_source("Fan Ho: A Hong Memoir 与街头光影几何研究")],
    engine_style="street",
    envelope=StyleEnvelope(
        exposure_ev=1.0,
        contrast=40,
        highlights=30,
        shadows=35,
        whites=25,
        blacks=30,
        saturation=100,
        clarity=25,
        vignette=15,
        grain=12,
    ),
    default_strength=0.6,
)

ANSEL_ADAMS = _profile(
    id="ansel_adams",
    kind=StyleKind.MASTER,
    name="Ansel Adams 黑白影调",
    description="以区域曝光体系实现从纯黑到纯白完整灰阶的风光黑白典范。",
    philosophy=(
        "预视（previsualization）：拍摄前即在脑海中完成最终影调，"
        "用完整的灰阶表达自然的庄严与细节，黑白不是缺色而是提纯。"
    ),
    color=StyleColorTraits(
        tendency="纯黑白，中性灰阶",
        relationships="以明度节奏组织画面，天空与大地形成影调对话",
        saturation="完全去饱和",
    ),
    light=StyleLightTraits(
        contrast="高对比但过渡完整，不死黑不死白",
        shadows="深黑中保留纹理（区域 II–III）",
        highlights="亮部细腻分层（区域 VII–VIII）",
        expression="自然光的时间性表达，晨光与暮光的影调差异",
    ),
    composition=StyleCompositionTraits(
        space="宏大纵深，前中远景层次分明",
        geometry="自然形态中的秩序感",
        negative_space="天空与暗部作为影调呼吸区",
        subject_relation="主体（山、树、水）以影调突出而非色彩",
    ),
    texture=StyleTextureTraits(
        grain="极细或无颗粒，追求平滑灰阶",
        sharpness="高锐度，细节纤毫毕现",
        detail="全画面细节最大化是核心追求",
    ),
    scene_fit=_scene_fit(
        suitable=["landscape", "nature"],
        suitable_notes="有丰富纹理与纵深层次的自然风光、山川、海岸",
        unsuitable_notes="依赖色彩表达主体的场景（如秋色、花卉特写）转黑白会损失信息",
    ),
    post_strategy=(
        "可转黑白、用 master 曲线建立完整灰阶、提升清晰度与细节，"
        "局部蒙版做 dodging/burning 式的明暗塑造，保护高光与阴影两端。"
    ),
    capture_techniques=(
        "无法创造不存在的景深层次与纹理细节；区域曝光的原始素材质量"
        "决定上限，严重欠曝或溢出的照片无法还原完整灰阶。"
    ),
    constraints=[
        DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
        DirectionConstraint.PRESERVE_SHADOW_DETAIL,
        DirectionConstraint.MAINTAIN_NEUTRALITY,
    ],
    preserve_notes="灰阶必须中性；不得为冲击力牺牲高光与阴影细节。",
    sources=[_source("Ansel Adams: The Camera / The Negative / The Print 区域曝光体系研究")],
    engine_style="landscape",
    envelope=StyleEnvelope(
        exposure_ev=1.0,
        contrast=45,
        highlights=40,
        shadows=40,
        whites=35,
        blacks=35,
        saturation=100,
        clarity=30,
        grain=8,
    ),
    default_strength=0.6,
)

HENRI_CARTIER_BRESSON = _profile(
    id="henri_cartier_bresson",
    kind=StyleKind.MASTER,
    name="Henri Cartier-Bresson 决定性瞬间",
    description="几何构图与人物瞬间精确合一的黑白纪实典范，后期极度克制。",
    philosophy=(
        "决定性瞬间：在几分之一秒内同时识别事件的意义与形式的严格组织，"
        "构图是几何直觉，裁剪被视为失败，后期只作最小限度影调调整。"
    ),
    color=StyleColorTraits(
        tendency="经典黑白，自然灰阶",
        relationships="形式关系优先于影调戏剧性",
        saturation="去饱和至单色",
    ),
    light=StyleLightTraits(
        contrast="中等对比，尊重现场光",
        shadows="自然保留，不刻意压暗",
        highlights="自然保留，不刻意提亮",
        expression="现场光的忠实记录，自然光美学",
    ),
    composition=StyleCompositionTraits(
        space="画面即完整构图，不依赖后期裁剪",
        geometry="黄金分割、对角线与重复形式的瞬间组织",
        negative_space="由场景自然形成",
        subject_relation="人物姿态与环境几何在瞬间达成平衡",
    ),
    texture=StyleTextureTraits(
        grain="自然胶片颗粒",
        sharpness="适中，不追求夸张锐化",
        detail="尊重原始记录的细节水平",
    ),
    scene_fit=_scene_fit(
        suitable=["street", "portrait"],
        suitable_notes="有人物活动、几何结构与瞬间张力的街头与纪实场景",
        unsuitable_notes="静态摆拍、缺少人物与环境互动的照片难以体现该风格核心",
    ),
    post_strategy=(
        "可转黑白并做温和影调调整（中等对比曲线、轻微清晰度），"
        "保持现场光关系；调整幅度应明显小于戏剧化黑白风格。"
    ),
    capture_techniques=(
        "决定性瞬间本身无法后期创造；人物姿态、事件时机与构图的同一性"
        "完全依赖拍摄，后期不得通过裁剪重构构图。"
    ),
    constraints=[
        DirectionConstraint.MAINTAIN_NEUTRALITY,
        DirectionConstraint.NATURAL_LOOK,
        DirectionConstraint.PRESERVE_SHADOW_DETAIL,
    ],
    preserve_notes="不得裁剪或重构画面几何；影调调整以不改变现场光感知为限。",
    sources=[_source("Henri Cartier-Bresson: The Decisive Moment (1952) 构图与瞬间研究")],
    engine_style="documentary",
    envelope=StyleEnvelope(
        contrast=25,
        highlights=20,
        shadows=25,
        saturation=100,
        clarity=15,
        grain=12,
    ),
    default_strength=0.5,
)

VIVIAN_MAIER = _profile(
    id="vivian_maier",
    kind=StyleKind.MASTER,
    name="Vivian Maier 人文纪实",
    description="以平等视角捕捉城市普通人自然情绪与街头剧场的低调纪实。",
    philosophy=(
        "隐身的观察者：用双反相机腰平取景，在不惊扰对象的前提下记录"
        "普通人的尊严、幽默与孤独，自拍与阴影游戏构成独特的自我在场。"
    ),
    color=StyleColorTraits(
        tendency="黑白为主，自然朴素的灰阶",
        relationships="影调服务于人物情绪而非形式炫耀",
        saturation="去饱和至单色，保留柔和中间调",
    ),
    light=StyleLightTraits(
        contrast="中低对比，柔和自然",
        shadows="开放阴影，保留环境信息",
        highlights="柔和亮部，不过分戏剧化",
        expression="城市自然光，阴天与建筑阴影下的柔光",
    ),
    composition=StyleCompositionTraits(
        space="近距离街拍，人物充满画面但不压迫",
        geometry="即兴而稳定的方形构图感",
        negative_space="由街道环境自然形成",
        subject_relation="人物与环境平等对话，背景保留叙事信息",
    ),
    texture=StyleTextureTraits(
        grain="中等胶片颗粒，朴素直接",
        sharpness="适中，焦点服务于人物",
        detail="保留衣着、表情与街道质感",
    ),
    scene_fit=_scene_fit(
        suitable=["street", "portrait"],
        suitable_notes="有真实人物状态与街道生活气息的纪实场景",
        unsuitable_notes="风光、建筑等无人文主体的照片不适合该风格",
    ),
    post_strategy=(
        "可转黑白、温和对比与柔和高光保护，保持自然观感；轻微颗粒增强纪实质感，避免任何夸张影调。"
    ),
    capture_techniques=(
        "无法创造人物的自然状态与街头相遇；摆拍感与过度后期都会破坏该风格的核心——不加干预的真实。"
    ),
    constraints=[
        DirectionConstraint.NATURAL_LOOK,
        DirectionConstraint.MAINTAIN_NEUTRALITY,
        DirectionConstraint.KEEP_AMBIENT_COLOR,
    ],
    preserve_notes="保护人物表情与身份特征；不得美化或戏剧化普通人的真实状态。",
    sources=[_source("Vivian Maier: Street Photographer (2011) 纪实语言研究")],
    engine_style="documentary",
    envelope=StyleEnvelope(
        contrast=22,
        highlights=20,
        shadows=22,
        saturation=100,
        grain=12,
        clarity=12,
    ),
    default_strength=0.5,
)

WILLIAM_EGGLESTON = _profile(
    id="william_eggleston",
    kind=StyleKind.MASTER,
    name="William Eggleston 日常色彩",
    description="以民主视角与染料转印式浓郁色彩把平凡日常拍成彩色艺术经典。",
    philosophy=(
        "民主的相机：任何事物都值得一拍，平凡场景与美国南方的日常色彩"
        "本身即主题；色彩不是装饰而是心理张力，快照式构图拒绝沙龙美学。"
    ),
    color=StyleColorTraits(
        tendency="浓郁但不艳俗的彩色，红与绿具有标志性地位",
        relationships="互补色并置产生心理张力（红天花板、绿三轮车）",
        saturation="中高饱和，染料转印式的色彩浓度",
    ),
    light=StyleLightTraits(
        contrast="中等对比，直射闪光与日光并用",
        shadows="保留现场阴影的直接感",
        highlights="容忍日常光的平淡，不刻意戏剧化",
        expression="美国南方强烈日光与室内混合光",
    ),
    composition=StyleCompositionTraits(
        space="快照式取景，主体常偏置或居中得理直气壮",
        geometry="日常物品的偶然几何",
        negative_space="由平凡环境自然形成",
        subject_relation="物与空间平等，无传统主次层级",
    ),
    texture=StyleTextureTraits(
        grain="细腻彩色胶片质感",
        sharpness="清晰直接",
        detail="日常物品表面质感被色彩放大",
    ),
    scene_fit=_scene_fit(
        suitable=["street", "indoor", "portrait"],
        suitable_notes="有鲜明色彩元素与日常物品张力的街头、室内环境人像",
        unsuitable_notes="灰暗单调、缺少色彩锚点的场景难以体现该风格",
    ),
    post_strategy=(
        "可适度提升 vibrance 与饱和、强化互补色分离（HSL 红/绿）、"
        "轻微暖调偏移；色彩浓度提升必须有原图色彩基础。"
    ),
    capture_techniques=(
        "无法把无色彩关系的场景变成色彩杰作；题材的民主性与快照构图"
        "依赖拍摄选择，后期不能重构题材意义。"
    ),
    constraints=[
        DirectionConstraint.AVOID_EXTREME_SATURATION,
        DirectionConstraint.KEEP_AMBIENT_COLOR,
        DirectionConstraint.NATURAL_LOOK,
    ],
    preserve_notes="色彩浓郁但不可溢出失真；保留日常光的直接感，不做影楼式美化。",
    sources=[_source("William Eggleston's Guide (MoMA, 1976) 彩色纪实研究")],
    engine_style="documentary",
    envelope=StyleEnvelope(
        contrast=18,
        temperature=12,
        saturation=35,
        vibrance=30,
        clarity=12,
        grain=10,
    ),
    default_strength=0.55,
)

STEVE_MCCURRY = _profile(
    id="steve_mccurry",
    kind=StyleKind.MASTER,
    name="Steve McCurry 环境人像",
    description="以互补色彩关系与柔和方向光讲述人物故事的国家地理式环境人像。",
    philosophy=(
        "人在环境中：寻找跨越文化的共同人性，用色彩关系（尤其红绿互补）"
        "与眼神光构建叙事，环境是人物故事的延伸而非背景板。"
    ),
    color=StyleColorTraits(
        tendency="浓郁而受控的彩色，暖调主导",
        relationships="互补色分离（红/橙 对 绿/青）组织画面",
        saturation="中高饱和但肤色保持可信",
    ),
    light=StyleLightTraits(
        contrast="中等对比，柔和过渡",
        shadows="开放而有细节，衬托面部",
        highlights="柔和受光面，保护肤色高光",
        expression="柔和方向光与黄金时刻，眼神光是关键",
    ),
    composition=StyleCompositionTraits(
        space="环境包裹人物，纵深讲述场所",
        geometry="人物位置与环境线条呼应",
        negative_space="环境虚化与暗部突出人物",
        subject_relation="人物绝对优先，环境提供叙事语境",
    ),
    texture=StyleTextureTraits(
        grain="极细，现代胶片感",
        sharpness="眼部与面部高锐度，环境适度柔和",
        detail="皮肤与织物质感丰富但不过分",
    ),
    scene_fit=_scene_fit(
        suitable=["portrait", "street"],
        suitable_notes="有环境语境、方向性柔光与色彩关系的人像",
        unsuitable_notes="棚拍纯色背景、无人物主体的风光不适合",
    ),
    post_strategy=(
        "可提升 vibrance、用色彩分级做暖调互补分离、局部蒙版突出人物"
        "并轻压背景饱和；肤色保护是硬约束。"
    ),
    capture_techniques=(
        "无法创造眼神光、真实表情与拍摄时的光线方向；"
        "环境叙事依赖现场选择，后期不能更换背景或重构人物。"
    ),
    constraints=[
        DirectionConstraint.PRESERVE_SKIN_TONE,
        DirectionConstraint.AVOID_EXTREME_SATURATION,
        DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
    ],
    preserve_notes="任何色彩强化不得使肤色偏移失真；人物身份特征绝对保护。",
    sources=[_source("Steve McCurry 环境人像与互补色彩关系研究（专题综述）")],
    engine_style="portrait",
    envelope=StyleEnvelope(
        contrast=20,
        highlights=20,
        shadows=20,
        temperature=10,
        saturation=25,
        vibrance=25,
        clarity=18,
    ),
    default_strength=0.55,
)

HIROSHI_SUGIMOTO = _profile(
    id="hiroshi_sugimoto",
    kind=StyleKind.MASTER,
    name="Hiroshi Sugimoto 极简时间",
    description="以海景二分构图与剧院整片曝光凝结时间的极简黑白观念摄影。",
    philosophy=(
        "时间的曝光：海景系列以水平线二分天地，剧院系列以整部电影时长"
        "曝光得到一片白光——摄影是时间的容器，极简形式承载观念重量。"
    ),
    color=StyleColorTraits(
        tendency="纯黑白，极细腻灰阶",
        relationships="明度渐变本身即内容",
        saturation="完全去饱和",
    ),
    light=StyleLightTraits(
        contrast="低对比，极柔和的渐变",
        shadows="灰而不黑，保留空气感",
        highlights="白而不溢，细腻分层",
        expression="长时间曝光带来的均质化光线",
    ),
    composition=StyleCompositionTraits(
        space="极致留白，水平线居中二分",
        geometry="极简对称与水平线秩序",
        negative_space="留白是主体而非剩余",
        subject_relation="无传统主体，天地/光与空间即主体",
    ),
    texture=StyleTextureTraits(
        grain="极细或无，平滑如镜面",
        sharpness="柔和，拒绝锐利边缘",
        detail="细节被时间抹平，渐变取代纹理",
    ),
    scene_fit=_scene_fit(
        suitable=["landscape", "architecture", "other"],
        suitable_notes="海平面、天空、极简建筑与大面积均质空间的场景",
        unsuitable_notes="元素繁杂、纹理密集、依赖细节叙事的照片",
    ),
    post_strategy=(
        "可转黑白、压缩对比至柔和渐变、保护两端细节、降低清晰度，"
        "保持留白区域的均质；调整必须极度克制。"
    ),
    capture_techniques=(
        "无法实现长曝光的时间抹平效果（水面雾化、移动消失）；"
        "极简构图依赖拍摄时的场景选择，后期不能删除画面元素。"
    ),
    constraints=[
        DirectionConstraint.MAINTAIN_NEUTRALITY,
        DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
        DirectionConstraint.PRESERVE_SHADOW_DETAIL,
        DirectionConstraint.AVOID_EXTREME_CONTRAST,
    ],
    preserve_notes="不得增加对比戏剧性；留白与渐变的均质感是该风格的底线。",
    sources=[_source("Hiroshi Sugimoto: Seascapes / Theaters 系列观念研究")],
    engine_style="cinematic",
    envelope=StyleEnvelope(
        exposure_ev=0.6,
        contrast=15,
        highlights=20,
        shadows=20,
        saturation=100,
        clarity=10,
        grain=6,
    ),
    default_strength=0.45,
)

BW_DOCUMENTARY = _profile(
    id="bw_documentary",
    kind=StyleKind.GENRE,
    name="黑白纪实",
    description="以黑白影调剥离色彩干扰、直面内容与情绪的经典纪实流派。",
    philosophy=(
        "去掉色彩让观者直面内容：黑白把注意力还给形式、光影与人的状态，"
        "影调控制服务于叙事真实而非形式炫技。"
    ),
    color=StyleColorTraits(
        tendency="中性黑白",
        relationships="明度对比组织视觉优先级",
        saturation="完全去饱和，灰阶自然",
    ),
    light=StyleLightTraits(
        contrast="中等偏高，依现场光而定",
        shadows="保留叙事所需的暗部信息",
        highlights="保护亮部细节",
        expression="尊重现场光，不伪造光效",
    ),
    composition=StyleCompositionTraits(
        space="内容驱动的取景",
        geometry="形式服务于叙事",
        negative_space="自然形成",
        subject_relation="主体明确，背景提供语境",
    ),
    texture=StyleTextureTraits(
        grain="适度胶片颗粒增强纪实感",
        sharpness="适中",
        detail="保留内容相关细节",
    ),
    scene_fit=_scene_fit(
        suitable=["street", "portrait", "other"],
        suitable_notes="人物活动、事件现场与形式感强的街头纪实",
        unsuitable_notes="以色彩为核心信息的场景（秋色、霓虹、花卉）",
    ),
    post_strategy=(
        "可转黑白、S 曲线拉开影调、适度颗粒与清晰度，局部明暗引导视线；影调强度依照片光线基础决定。"
    ),
    capture_techniques=(
        "无法创造事件与人物状态；色彩信息一旦去除不可逆，需确认色彩不承担关键叙事后再转黑白。"
    ),
    constraints=[
        DirectionConstraint.MAINTAIN_NEUTRALITY,
        DirectionConstraint.PRESERVE_SHADOW_DETAIL,
        DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
    ],
    preserve_notes="灰阶中性不偏色；内容真实优先于影调冲击。",
    sources=[_source("FRAME AI 摄影流派原创整理：黑白纪实")],
    engine_style="documentary",
    envelope=StyleEnvelope(
        contrast=30,
        highlights=25,
        shadows=30,
        saturation=100,
        clarity=18,
        grain=12,
    ),
    default_strength=0.5,
)

POETIC_STREET = _profile(
    id="poetic_street",
    kind=StyleKind.GENRE,
    name="诗意街头",
    description="在街头日常中寻找抒情瞬间：柔和光线、色彩回声与人的孤独感。",
    philosophy=(
        "街头不是猎奇而是抒情：雨、雾、橱窗与行人构成城市诗篇，"
        "色彩与光线营造情绪氛围，瞬间带有温柔的疏离感。"
    ),
    color=StyleColorTraits(
        tendency="低饱和冷暖交织，偏青蓝或暖黄的城市色调",
        relationships="色彩回声（重复出现的色块）串联画面",
        saturation="中低饱和，情绪化而非记录化",
    ),
    light=StyleLightTraits(
        contrast="中低对比，柔和氛围",
        shadows="开放灰暗部",
        highlights="柔化亮部，容忍光晕",
        expression="雨天、黄昏与橱窗光的情绪光线",
    ),
    composition=StyleCompositionTraits(
        space="层次与遮挡制造抒情距离",
        geometry="松散平衡，非严格几何",
        negative_space="雾气、墙面与暗部留白",
        subject_relation="孤身人物与城市环境的对话",
    ),
    texture=StyleTextureTraits(
        grain="细腻颗粒",
        sharpness="偏柔",
        detail="氛围优先于纤毫细节",
    ),
    scene_fit=_scene_fit(
        suitable=["street", "night", "architecture"],
        suitable_notes="有天气氛围、光线情绪与行人元素的城市街头",
        unsuitable_notes="正午硬光、杂乱无情绪锚点的场景",
    ),
    post_strategy=(
        "可柔化对比、统一色调（轻色彩分级）、轻暗角与细颗粒，"
        "局部压暗背景突出人物；氛围调整以原图光线为基础。"
    ),
    capture_techniques=(
        "无法创造雨雾天气与抒情瞬间；氛围依赖拍摄时机，后期只能强化已有情绪而不能无中生有。"
    ),
    constraints=[
        DirectionConstraint.KEEP_AMBIENT_COLOR,
        DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
        DirectionConstraint.AVOID_EXTREME_SATURATION,
    ],
    preserve_notes="保留现场氛围色温；不做高对比硬调或过度 HDR 感。",
    sources=[_source("FRAME AI 摄影流派原创整理：诗意街头")],
    engine_style="street",
    envelope=StyleEnvelope(
        contrast=25,
        highlights=22,
        temperature=12,
        saturation=30,
        vibrance=18,
        vignette=18,
        grain=12,
    ),
    default_strength=0.5,
)

CINEMATIC_NARRATIVE = _profile(
    id="cinematic_narrative",
    kind=StyleKind.GENRE,
    name="电影叙事",
    description="以电影感色罩、宽银幕影调与明暗叙事让照片像一帧剧照。",
    philosophy=(
        "照片即剧照：用电影调色语言（青橙分离、暗部色罩、柔和高光滚降）"
        "营造叙事张力，光线与色彩暗示画外故事。"
    ),
    color=StyleColorTraits(
        tendency="青橙互补或自定义色罩，暗部偏冷亮部偏暖",
        relationships="三区色彩分级建立电影感分离",
        saturation="中等饱和，肤色区域受保护",
    ),
    light=StyleLightTraits(
        contrast="中高对比，电影式影调",
        shadows="压暗但带色罩与细节",
        highlights="柔和滚降，不刺眼",
        expression="方向性叙事光，明暗引导视线",
    ),
    composition=StyleCompositionTraits(
        space="纵深与画框感",
        geometry="引导线与视线空间",
        negative_space="暗部承担画外想象",
        subject_relation="主体处于叙事光区",
    ),
    texture=StyleTextureTraits(
        grain="细颗粒模拟胶片放映质感",
        sharpness="适中偏柔",
        detail="中间调丰富",
    ),
    scene_fit=_scene_fit(
        suitable=["street", "portrait", "night", "indoor"],
        suitable_notes="有方向光、人物或空间叙事潜力的场景",
        unsuitable_notes="光线完全平坦、无叙事主体的纯记录照片",
    ),
    post_strategy=(
        "可用色彩分级三区色罩、曲线压暗部提中间调、轻暗角与颗粒，"
        "局部曝光突出叙事主体；色罩强度受肤色保护约束。"
    ),
    capture_techniques=(
        "无法添加不存在的光源、烟雾或场景元素；电影感依赖原图"
        "已有的光线结构，生成式场景修改不属于本流派范围。"
    ),
    constraints=[
        DirectionConstraint.PRESERVE_SKIN_TONE,
        DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
        DirectionConstraint.AVOID_EXTREME_SATURATION,
    ],
    preserve_notes="色罩不得污染肤色；暗部压暗必须保留可辨细节。",
    sources=[_source("FRAME AI 摄影流派原创整理：电影叙事")],
    engine_style="cinematic",
    envelope=StyleEnvelope(
        contrast=30,
        highlights=25,
        shadows=28,
        temperature=18,
        tint=10,
        saturation=25,
        vignette=20,
        grain=10,
    ),
    default_strength=0.6,
)

RETRO_FILM = _profile(
    id="retro_film",
    kind=StyleKind.GENRE,
    name="复古胶片",
    description="模拟经典彩色负片的褪色暖调、柔和反差与可见颗粒的怀旧流派。",
    philosophy=(
        "时间的包浆：褪色高光、抬升黑位、暖调偏移与颗粒共同制造被岁月抚摸过的记忆感，不完美即真实。"
    ),
    color=StyleColorTraits(
        tendency="暖调褪色，黄绿倾向的旧照片色偏",
        relationships="低对比色彩关系，褪色感",
        saturation="中低饱和，色彩微微失真但和谐",
    ),
    light=StyleLightTraits(
        contrast="低中对比，黑位抬升（fade）",
        shadows="抬升发灰，保留旧照片空气感",
        highlights="柔和微黄，不追求纯白",
        expression="模拟胶片宽容度的柔光表达",
    ),
    composition=StyleCompositionTraits(
        space="快照式随意感",
        geometry="不强调严格几何",
        negative_space="自然形成",
        subject_relation="日常主体，记忆片段感",
    ),
    texture=StyleTextureTraits(
        grain="明显但均匀的胶片颗粒是该流派标志",
        sharpness="偏柔，轻微光晕",
        detail="颗粒覆盖下的适中细节",
    ),
    scene_fit=_scene_fit(
        suitable=["street", "portrait", "indoor", "nature"],
        suitable_notes="日常记录、旅行随拍与有年代感潜力的场景",
        unsuitable_notes="需要精准色彩还原的商业与产品摄影",
    ),
    post_strategy=(
        "可用曲线抬黑压白制造 fade、暖调偏移、降饱和、加颗粒与轻暗角；"
        "HSL 轻调黄绿通道模拟负片色偏。"
    ),
    capture_techniques=(
        "无法真正还原特定胶片乳剂的色彩科学；模拟是风格化近似，不能宣称等同某型号胶片的真实输出。"
    ),
    constraints=[
        DirectionConstraint.KEEP_WARM_TONES,
        DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
        DirectionConstraint.AVOID_EXTREME_SATURATION,
    ],
    preserve_notes="褪色不丢失全部层次；颗粒强度以不掩盖主体细节为限。",
    sources=[_source("FRAME AI 摄影流派原创整理：复古胶片")],
    engine_style="film",
    envelope=StyleEnvelope(
        contrast=20,
        highlights=20,
        blacks=25,
        temperature=15,
        saturation=25,
        vibrance=15,
        vignette=15,
        grain=30,
    ),
    default_strength=0.55,
)

MINIMAL_ARCHITECTURE = _profile(
    id="minimal_architecture",
    kind=StyleKind.GENRE,
    name="极简建筑",
    description="以几何秩序、负空间与克制影调提炼建筑的形式本质。",
    philosophy=("少即多：剥离杂乱环境，让线条、体块、光影与负空间自己说话，建筑摄影是几何的肖像。"),
    color=StyleColorTraits(
        tendency="中性或单色倾向，色彩极度克制",
        relationships="材质本色与天空的简洁对话",
        saturation="低饱和，可接近单色",
    ),
    light=StyleLightTraits(
        contrast="中高对比，强化体块",
        shadows="干净利落，形状明确",
        highlights="保护立面细节",
        expression="硬光下的几何阴影或均质柔光",
    ),
    composition=StyleCompositionTraits(
        space="极致负空间，主体孤立",
        geometry="对称、重复、对角线的严格秩序",
        negative_space="天空与墙面大面积留白",
        subject_relation="建筑局部即主体，环境被最小化",
    ),
    texture=StyleTextureTraits(
        grain="无或极细",
        sharpness="高锐度突出线条",
        detail="材质纹理清晰但干净",
    ),
    scene_fit=_scene_fit(
        suitable=["architecture", "other"],
        suitable_notes="有简洁几何、干净背景与明确光影的建筑局部",
        unsuitable_notes="杂乱街景、元素过多的环境无法极简化的照片",
    ),
    post_strategy=(
        "可提清晰度、强化对比与黑白灰关系、局部压暗杂乱区域、轻去饱和统一色调；不能移除画面元素。"
    ),
    capture_techniques=(
        "无法删除电线、行人等杂乱元素（属生成式编辑，V6.3 范围）；极简构图依赖拍摄时的取景与等待。"
    ),
    constraints=[
        DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
        DirectionConstraint.AVOID_EXTREME_CONTRAST,
        DirectionConstraint.MAINTAIN_NEUTRALITY,
    ],
    preserve_notes="线条与透视不得扭曲变形；留白区域的均质性必须保持。",
    sources=[_source("FRAME AI 摄影流派原创整理：极简建筑")],
    engine_style="natural",
    envelope=StyleEnvelope(
        contrast=25,
        highlights=25,
        blacks=25,
        saturation=20,
        clarity=25,
        grain=6,
    ),
    default_strength=0.5,
)

NATURE_LANDSCAPE = _profile(
    id="nature_landscape",
    kind=StyleKind.GENRE,
    name="自然风光",
    description="在自然原色基础上强化层次与光线感染力的风光流派。",
    philosophy=(
        "自然的庄严与生机：尊重现场色彩与光线，通过层次、细节与"
        "适度色彩强化让观者感受到身临其境的自然力量。"
    ),
    color=StyleColorTraits(
        tendency="自然原色强化，天空青蓝与植被绿意的健康表达",
        relationships="冷暖分区（天空冷、受光面暖）",
        saturation="中等偏高但不过饱和，vibrance 优先",
    ),
    light=StyleLightTraits(
        contrast="中等对比，层次丰富",
        shadows="开放细节，不死黑",
        highlights="严格保护天空与水面高光",
        expression="黄金时刻与蓝色时刻的自然光魅力",
    ),
    composition=StyleCompositionTraits(
        space="前中远景纵深层次",
        geometry="引导线与三分法",
        negative_space="天空与水面留白",
        subject_relation="自然主体（山、水、树）明确",
    ),
    texture=StyleTextureTraits(
        grain="无或极细",
        sharpness="高锐度展现自然纹理",
        detail="最大化但避免光晕伪影",
    ),
    scene_fit=_scene_fit(
        suitable=["landscape", "nature"],
        suitable_notes="山川、海岸、森林、天空等自然场景",
        unsuitable_notes="城市街景与人像不是该流派目标",
    ),
    post_strategy=(
        "可提升 vibrance 与适度饱和、分区色彩调整（HSL 蓝/绿）、"
        "曲线拉开层次、局部提亮主体压暗边缘、保护高光。"
    ),
    capture_techniques=(
        "无法创造不存在的云层、光线时刻或景深层次；严重光比失衡的素材需要包围曝光而非单张硬拉。"
    ),
    constraints=[
        DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
        DirectionConstraint.AVOID_EXTREME_SATURATION,
        DirectionConstraint.PRESERVE_SHADOW_DETAIL,
    ],
    preserve_notes="色彩强化不得出现荧光感与色带；天空高光必须保留层次。",
    sources=[_source("FRAME AI 摄影流派原创整理：自然风光")],
    engine_style="landscape",
    envelope=StyleEnvelope(
        contrast=25,
        highlights=30,
        shadows=25,
        saturation=20,
        vibrance=25,
        clarity=20,
    ),
    default_strength=0.5,
)

ENVIRONMENTAL_PORTRAIT = _profile(
    id="environmental_portrait",
    kind=StyleKind.GENRE,
    name="环境人像",
    description="让人物与其场所互相讲述：环境提供身份语境的人像流派。",
    philosophy=(
        "人在其所在：工作间、街道、家园是人物身份的延伸，"
        "环境细节与人物状态共同构成完整叙事，肤色与眼神永远优先。"
    ),
    color=StyleColorTraits(
        tendency="自然和谐的环境色，人物肤色为基准",
        relationships="环境色与衣着/肤色的呼应或对比",
        saturation="中等，环境可略降以突出人物",
    ),
    light=StyleLightTraits(
        contrast="中等对比，面部柔和",
        shadows="环境阴影保留语境",
        highlights="保护面部受光面",
        expression="现场方向光与窗光的自然运用",
    ),
    composition=StyleCompositionTraits(
        space="环境包裹人物，纵深适度",
        geometry="环境线条指向人物",
        negative_space="环境虚化区",
        subject_relation="人物优先，环境叙事",
    ),
    texture=StyleTextureTraits(
        grain="极细",
        sharpness="面部锐利，环境适度柔和",
        detail="皮肤质感自然，环境细节可读",
    ),
    scene_fit=_scene_fit(
        suitable=["portrait", "street", "indoor"],
        suitable_notes="有身份语境环境与自然光的人像",
        unsuitable_notes="纯色背景棚拍与无人物的环境照片",
    ),
    post_strategy=(
        "可温和影调调整、vibrance 提升、局部蒙版突出人物（轻压背景"
        "饱和与曝光）、肤色保护下的色彩分级。"
    ),
    capture_techniques=(
        "无法更换背景、创造眼神光或改变人物姿态表情；环境叙事依赖拍摄时的场所选择与沟通。"
    ),
    constraints=[
        DirectionConstraint.PRESERVE_SKIN_TONE,
        DirectionConstraint.NATURAL_LOOK,
        DirectionConstraint.KEEP_AMBIENT_COLOR,
    ],
    preserve_notes="肤色自然第一；环境调整不得喧宾夺主或改变场所真实感。",
    sources=[_source("FRAME AI 摄影流派原创整理：环境人像")],
    engine_style="portrait",
    envelope=StyleEnvelope(
        contrast=18,
        highlights=20,
        shadows=20,
        saturation=18,
        vibrance=20,
        clarity=15,
    ),
    default_strength=0.5,
)

NIGHT_PHOTOGRAPHY = _profile(
    id="night_photography",
    kind=StyleKind.GENRE,
    name="夜景摄影",
    description="在暗部细节、灯光色彩与城市夜色氛围之间取得平衡的夜景流派。",
    philosophy=(
        "夜不是黑：城市灯光、霓虹与天空余晖构成独特的色彩世界，"
        "夜景的魅力在于暗中有物、光中有彩、静中有动。"
    ),
    color=StyleColorTraits(
        tendency="混合光源色彩（钠灯橙、LED 冷白、霓虹彩）",
        relationships="冷暖光源交错，白平衡取舍表达氛围",
        saturation="灯光区域中高饱和，暗部低饱和",
    ),
    light=StyleLightTraits(
        contrast="高动态范围场景，需压缩光比",
        shadows="提亮暗部但控制噪声",
        highlights="严格保护灯光与招牌不过曝",
        expression="人工光源主导的夜色氛围",
    ),
    composition=StyleCompositionTraits(
        space="灯光引导的城市纵深",
        geometry="道路线条与建筑轮廓",
        negative_space="夜空与暗部",
        subject_relation="灯光区域与行人/车流主体",
    ),
    texture=StyleTextureTraits(
        grain="噪声控制优先，颗粒克制",
        sharpness="适中，避免锐化放大噪声",
        detail="暗部细节与灯光纹理的平衡",
    ),
    scene_fit=_scene_fit(
        suitable=["night", "street", "architecture"],
        suitable_notes="城市灯光、霓虹、车流与建筑夜景",
        unsuitable_notes="纯黑暗无细节可提的素材、白天场景",
    ),
    post_strategy=(
        "可温和提曝光、压高光保灯光、提阴影并降噪、分区白平衡调整"
        "（HSL 橙/蓝）、轻色彩分级统一夜色；降噪与细节需平衡。"
    ),
    capture_techniques=(
        "无法恢复完全死黑的无信息暗部；车流光轨与长曝效果依赖拍摄，后期不能伪造光轨。"
    ),
    constraints=[
        DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
        DirectionConstraint.PRESERVE_SHADOW_DETAIL,
        DirectionConstraint.AVOID_COLOR_CAST,
        DirectionConstraint.KEEP_AMBIENT_COLOR,
    ],
    preserve_notes="灯光色彩是夜色灵魂，不得全局白平衡抹平；暗部提亮以噪声可控为限。",
    sources=[_source("FRAME AI 摄影流派原创整理：夜景摄影")],
    engine_style="cinematic",
    envelope=StyleEnvelope(
        exposure_ev=1.0,
        contrast=22,
        highlights=30,
        shadows=30,
        temperature=15,
        saturation=25,
        denoise=35,
        clarity=15,
    ),
    default_strength=0.5,
)

SEED_PROFILES: tuple[StyleProfile, ...] = (
    SAUL_LEITER,
    FAN_HO,
    ANSEL_ADAMS,
    HENRI_CARTIER_BRESSON,
    VIVIAN_MAIER,
    WILLIAM_EGGLESTON,
    STEVE_MCCURRY,
    HIROSHI_SUGIMOTO,
    BW_DOCUMENTARY,
    POETIC_STREET,
    CINEMATIC_NARRATIVE,
    RETRO_FILM,
    MINIMAL_ARCHITECTURE,
    NATURE_LANDSCAPE,
    ENVIRONMENTAL_PORTRAIT,
    NIGHT_PHOTOGRAPHY,
)


@dataclass(frozen=True, slots=True)
class SeedResult:
    created: tuple[str, ...]
    skipped: tuple[str, ...]


def seed_style_library(repository: SqliteStyleProfileRepository) -> SeedResult:
    created: list[str] = []
    skipped: list[str] = []
    for profile in SEED_PROFILES:
        if repository.get(profile.id) is None:
            repository.create(profile)
            created.append(profile.id)
        else:
            skipped.append(profile.id)
    return SeedResult(created=tuple(created), skipped=tuple(skipped))


__all__ = ["SEED_PROFILES", "SeedResult", "seed_style_library"]
