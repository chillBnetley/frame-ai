import Link from "next/link";

export interface PrivacyPoint {
  title: string;
  body: string;
}

export const PRIVACY_POINTS: PrivacyPoint[] = [
  {
    title: "哪些照片会被用于分析",
    body: "只有你在参考照片中主动选择并勾选授权的照片会参与本风格分析；未授权的照片不会进入分析。",
  },
  {
    title: "分析会提取哪些信息",
    body: "提取色彩、影调、光线、质感、构图与场景等可解释的视觉特征，用于生成个人风格档案；不提取人脸身份信息。",
  },
  {
    title: "是否会调用第三方模型",
    body: "个人风格的特征提取与融合在本机完成，不调用外部模型。若你在设置中启用了外部 AI Provider，你单独发起的图像分析请求会使用该 Provider，仅用于该次分析。",
  },
  {
    title: "图片是否会被保存",
    body: "原始图片保存在你的本地图片库；个人风格只保存参考关系与提取特征，不复制原始图片。",
  },
  {
    title: "如何撤回授权或删除参考照片",
    body: "在个人风格详情的参考照片列表点击「撤回授权」，会立即停止使用该照片并删除它的提取特征；你的原始图片会保留。",
  },
  {
    title: "如何删除个人风格",
    body: "在风格详情点击「删除」并确认，会删除风格档案、所有版本、参考关联、提取特征、反馈与演变记录；原始图片不会被删除。",
  },
  {
    title: "不会默认用于模型训练",
    body: "参考照片与提取特征不会用于训练任何模型。",
  },
  {
    title: "默认私有，不会自动公开",
    body: "新建的个人风格默认为草稿，仅你可见；只有你主动发布后，才会出现在可选择的风格列表中。",
  },
];

export function PrivacyNotice() {
  return (
    <section
      aria-labelledby="privacy-heading"
      className="rounded-2xl border border-[#dfe5e1] bg-white p-5 shadow-[0_24px_60px_-55px_rgba(20,45,34,0.5)] sm:p-6"
    >
      <p className="text-[10px] font-semibold uppercase tracking-[0.28em] text-[#8a9a93]">
        PRIVACY &amp; CONSENT
      </p>
      <h1
        id="privacy-heading"
        className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[#1d2521]"
      >
        隐私与授权说明
      </h1>
      <p className="mt-2 max-w-3xl text-sm leading-relaxed text-[#66716b]">
        参考照片与个人风格属于你的私人创作资产。下面说明数据如何被使用、如何撤回授权，以及删除时会处理哪些内容。
      </p>
      <ul className="mt-5 grid gap-3 sm:grid-cols-2">
        {PRIVACY_POINTS.map((point) => (
          <li
            key={point.title}
            className="rounded-xl border border-[#e4e8e5] bg-[#f9fbf9] p-4"
          >
            <h2 className="text-xs font-semibold text-[#2a3530]">{point.title}</h2>
            <p className="mt-1.5 text-[11px] leading-relaxed text-[#6b7a73]">{point.body}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function PrivacySummary() {
  return (
    <section
      aria-labelledby="privacy-summary-heading"
      className="rounded-xl border border-[#dfe5e1] bg-[#f9fbf9] p-4 text-[11px] leading-relaxed text-[#7a8680]"
    >
      <h2 id="privacy-summary-heading" className="font-semibold text-[#55625b]">
        隐私与授权
      </h2>
      <p className="mt-1">
        参考照片仅在你主动授权后用于本风格分析，不用于模型训练，也不会自动公开。
        撤回授权会删除该照片的提取特征，但会保留你的原始图片。
      </p>
      <Link
        href="/visual-dna/privacy"
        className="mt-2 inline-flex min-h-8 items-center text-[11px] font-medium text-[#277a68] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        查看完整授权说明
      </Link>
    </section>
  );
}
