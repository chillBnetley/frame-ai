"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/visual-dna", label: "我的风格" },
  { href: "/visual-dna/new", label: "参考照片创建" },
  { href: "/visual-dna/custom", label: "自然语言创建" },
  { href: "/visual-dna/mix", label: "风格混合" },
  { href: "/visual-dna/privacy", label: "隐私与授权" },
  { href: "/master-vision/masters", label: "大师风格" },
];

export function VisualDnaNav() {
  const pathname = usePathname() ?? "";

  return (
    <nav
      aria-label="Visual DNA 导航"
      className="flex flex-wrap items-center gap-1 border-b border-[#e4e8e5] pb-3"
    >
      {LINKS.map((link) => {
        const active =
          link.href === "/visual-dna"
            ? pathname === link.href ||
              (pathname.startsWith("/visual-dna/") &&
                !pathname.startsWith("/visual-dna/new") &&
                !pathname.startsWith("/visual-dna/custom") &&
                !pathname.startsWith("/visual-dna/mix") &&
                !pathname.startsWith("/visual-dna/privacy"))
            : pathname.startsWith(link.href);
        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={active ? "page" : undefined}
            className={[
              "inline-flex min-h-9 items-center rounded-full px-3.5 text-xs font-medium tracking-[0.02em] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
              active
                ? "bg-[#eaf3ef] text-[#1f6a5a]"
                : "text-[#69716c] hover:bg-[#f1f4f2] hover:text-[#2c3a34]",
            ].join(" ")}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
