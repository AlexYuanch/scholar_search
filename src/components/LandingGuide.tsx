import { useState } from "react"
import {
  ArrowUpRight,
  Bell,
  BookMarked,
  CheckCircle2,
  CircleAlert,
  Clock3,
  GitBranch,
  History,
  ScanSearch,
  SearchCheck,
  Sparkles,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import type { Lang } from "@/i18n"

interface Props {
  lang: Lang
  onTryExample: () => void
  t: (key: string) => string
}

type CaseKey = "candidate" | "workflow" | "overview" | "collaboration" | "history" | "tracking"

function CandidateDemo({ lang }: { lang: Lang }) {
  const zh = lang === "zh"
  return (
    <div className="scholar-demo-candidates">
      <div className="scholar-demo-toolbar">
        <span>{zh ? "3 位同名学者" : "3 namesake scholars"}</span>
        <small>{zh ? "按身份依据排序" : "Sorted by identity evidence"}</small>
      </div>
      {[
        ["F. Li", "Stanford University", "ORCID · 593", true],
        ["F. Li", "University of Electronic Science and Technology", "126", false],
        ["F. Li", "Chinese Academy of Sciences", "84", false],
      ].map(([name, institution, detail, active]) => (
        <article key={institution as string} className={active ? "is-active" : ""}>
          <span>{name}</span>
          <div><strong>{institution}</strong><small>{detail} {zh ? "篇论文" : "papers"}</small></div>
          {active && <CheckCircle2 />}
        </article>
      ))}
    </div>
  )
}

function WorkflowDemo({ lang }: { lang: Lang }) {
  const zh = lang === "zh"
  return (
    <div className="scholar-demo-workflow">
      <header>
        <Clock3 />
        <div>
          <strong>{zh ? "画像正在后台生成" : "Profile is building in the background"}</strong>
          <span>{zh ? "离开此页不会中断任务" : "You can leave without interrupting the job"}</span>
        </div>
        <em>{zh ? "处理中" : "Running"}</em>
      </header>
      <ol>
        {[
          zh ? "核验学者身份" : "Verify identity",
          zh ? "汇总并核对论文" : "Reconcile publications",
          zh ? "分析研究轨迹与合作" : "Analyze trajectory and collaboration",
          zh ? "复核结论依据" : "Review evidence",
        ].map((label, index) => (
          <li key={label} className={index < 2 ? "is-complete" : index === 2 ? "is-running" : ""}>
            <span>{index < 2 ? "✓" : index + 1}</span>{label}
          </li>
        ))}
      </ol>
      <footer><History />{zh ? "查询历史中同步显示：处理中" : "History simultaneously shows: running"}</footer>
    </div>
  )
}

function OverviewDemo({ lang }: { lang: Lang }) {
  const zh = lang === "zh"
  return (
    <div className="scholar-demo-overview">
      <header>
        <div className="scholar-demo-avatar">FL</div>
        <div><strong>{zh ? "示例学者" : "Example scholar"}</strong><span>Stanford University</span></div>
      </header>
      <div className="scholar-demo-metrics">
        <p><strong>593</strong><span>{zh ? "收录论文" : "papers"}</span></p>
        <p><strong>217k</strong><span>{zh ? "引用" : "citations"}</span></p>
        <p><strong>133</strong><span>h-index</span></p>
      </div>
      <section>
        <small>{zh ? "主要研究方向" : "Research directions"}</small>
        <div><span>Computer Vision</span><span>Visual Recognition</span><span>AI for Healthcare</span></div>
      </section>
      <p>{zh ? "从代表作、时间线和近期变化理解研究延续性，而非只看论文数量。" : "Read representative works, timelines, and recent shifts—not publication counts alone."}</p>
    </div>
  )
}

function CollaborationDemo({ lang }: { lang: Lang }) {
  const zh = lang === "zh"
  const [selected, setSelected] = useState<"node" | "edge">("node")
  return (
    <div className="scholar-demo-network">
      <p>{zh ? "试着点击节点或连线" : "Try selecting a node or an edge"}</p>
      <div>
        <svg viewBox="0 0 620 300" role="img" aria-label={zh ? "可交互合作网络示例" : "Interactive collaboration network example"}>
          <g
            role="button"
            tabIndex={0}
            className={selected === "edge" ? "is-selected" : ""}
            onClick={() => setSelected("edge")}
            onKeyDown={(event) => event.key === "Enter" && setSelected("edge")}
          >
            <line x1="310" y1="150" x2="485" y2="78" />
            <line className="hit-area" x1="310" y1="150" x2="485" y2="78" />
          </g>
          <line x1="310" y1="150" x2="515" y2="218" />
          <line x1="310" y1="150" x2="120" y2="82" />
          <line x1="310" y1="150" x2="108" y2="225" />
          <circle className="center" cx="310" cy="150" r="42" />
          <text x="310" y="155" textAnchor="middle">Scholar</text>
          <g
            role="button"
            tabIndex={0}
            className={selected === "node" ? "is-selected" : ""}
            onClick={() => setSelected("node")}
            onKeyDown={(event) => event.key === "Enter" && setSelected("node")}
          >
            <circle cx="485" cy="78" r="30" />
            <text x="485" y="83" textAnchor="middle">Peer A</text>
          </g>
          <circle cx="515" cy="218" r="25" /><text x="515" y="223" textAnchor="middle">Peer B</text>
          <circle cx="120" cy="82" r="27" /><text x="120" y="87" textAnchor="middle">Peer C</text>
          <circle cx="108" cy="225" r="23" /><text x="108" y="230" textAnchor="middle">Peer D</text>
        </svg>
        <aside>
          <strong>{selected === "node" ? (zh ? "合作者详情" : "Collaborator") : (zh ? "共同论文" : "Shared papers")}</strong>
          <span>{selected === "node"
            ? (zh ? "长期合作 18 篇 · 可主动查看其画像" : "18 long-term collaborations · open their profile")
            : (zh ? "点击连线查看 18 篇共同论文与合作主题" : "Select the edge to inspect 18 papers and shared topics")}</span>
        </aside>
      </div>
    </div>
  )
}

function HistoryDemo({ lang }: { lang: Lang }) {
  const zh = lang === "zh"
  return (
    <div className="scholar-demo-history">
      <header><History />{zh ? "查询历史" : "Query history"}</header>
      {[
        [zh ? "正在分析的学者" : "Scholar being analyzed", zh ? "处理中" : "Running", "running"],
        [zh ? "近期查询的学者" : "Recently viewed scholar", zh ? "可查看画像" : "Ready", "ready"],
        [zh ? "已完成的画像" : "Completed profile", zh ? "可查看画像" : "Ready", "ready"],
      ].map(([name, status, kind]) => (
        <article key={name}>
          <div><strong>{name}</strong><span>University · OpenAlex</span></div>
          <em className={kind}>{kind === "running" && <Clock3 />}{status}</em>
        </article>
      ))}
    </div>
  )
}

function TrackingDemo({ lang }: { lang: Lang }) {
  const zh = lang === "zh"
  return (
    <div className="scholar-demo-tracking">
      <header><Bell />{zh ? "研究追踪" : "Research tracking"}<span>{zh ? "2 项新进展" : "2 updates"}</span></header>
      <article>
        <small>{zh ? "新论文" : "New publication"}</small>
        <strong>Foundation Models for Visual Intelligence</strong>
        <span>2026 · +148 {zh ? "次引用" : "citations"}</span>
      </article>
      <article>
        <small>{zh ? "方向变化" : "Direction shift"}</small>
        <strong>{zh ? "视觉基础模型持续上升" : "Visual foundation models continue to rise"}</strong>
        <span>{zh ? "依据近期论文主题与时间线判断" : "Based on recent paper topics and timeline evidence"}</span>
      </article>
    </div>
  )
}

function CaseDemo({ activeCase, lang }: { activeCase: CaseKey; lang: Lang }) {
  if (activeCase === "candidate") return <CandidateDemo lang={lang} />
  if (activeCase === "workflow") return <WorkflowDemo lang={lang} />
  if (activeCase === "overview") return <OverviewDemo lang={lang} />
  if (activeCase === "collaboration") return <CollaborationDemo lang={lang} />
  if (activeCase === "history") return <HistoryDemo lang={lang} />
  return <TrackingDemo lang={lang} />
}

export default function LandingGuide({ lang, onTryExample, t }: Props) {
  const [activeCase, setActiveCase] = useState<CaseKey>("candidate")
  const steps = [
    { icon: ScanSearch, title: t("guide.step_search"), text: t("guide.step_search_desc") },
    { icon: SearchCheck, title: t("guide.step_identify"), text: t("guide.step_identify_desc") },
    { icon: BookMarked, title: t("guide.step_read"), text: t("guide.step_read_desc") },
  ]
  const cases: Array<{ key: CaseKey; title: string; text: string }> = [
    { key: "candidate", title: t("guide.case_candidate"), text: t("guide.case_candidate_desc") },
    { key: "workflow", title: t("guide.case_workflow"), text: t("guide.case_workflow_desc") },
    { key: "overview", title: t("guide.case_overview"), text: t("guide.case_overview_desc") },
    { key: "collaboration", title: t("guide.case_collaboration"), text: t("guide.case_collaboration_desc") },
    { key: "history", title: t("guide.case_history"), text: t("guide.case_history_desc") },
    { key: "tracking", title: t("guide.case_tracking"), text: t("guide.case_tracking_desc") },
  ]
  const active = cases.find((item) => item.key === activeCase) ?? cases[0]

  return (
    <div className="scholar-guide">
      <section className="scholar-guide-start" aria-labelledby="guide-start-title">
        <div className="scholar-guide-heading" data-scholar-reveal="up">
          <p>{t("guide.label")}</p>
          <h2 id="guide-start-title">{t("guide.title")}</h2>
          <span>{t("guide.description")}</span>
        </div>
        <div className="scholar-guide-steps">
          {steps.map(({ icon: Icon, title, text }, index) => (
            <article key={title} data-scholar-reveal="up">
              <div><Icon /><span>0{index + 1}</span></div>
              <h3>{title}</h3>
              <p>{text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="scholar-case-study" aria-labelledby="case-study-title">
        <div className="scholar-case-intro" data-scholar-reveal="up">
          <div><p>{t("guide.case_label")}</p><h2 id="case-study-title">{t("guide.case_title")}</h2></div>
          <p>{t("guide.case_description")}</p>
        </div>

        <div className="scholar-case-layout">
          <div className="scholar-case-viewer" data-scholar-reveal="left">
            <div className="scholar-case-tabs" role="tablist" aria-label={t("guide.case_title")}>
              {cases.map((item) => (
                <button type="button" role="tab" aria-selected={activeCase === item.key} key={item.key} onClick={() => setActiveCase(item.key)}>
                  {item.title}
                </button>
              ))}
            </div>
            <div className="scholar-case-screen scholar-case-screen--live">
              <CaseDemo activeCase={activeCase} lang={lang} />
            </div>
            <div className="scholar-case-caption"><strong>{active.title}</strong><span>{active.text}</span></div>
          </div>

          <aside className="scholar-case-findings" data-scholar-reveal="right">
            <p className="scholar-case-kicker"><Sparkles />{t("guide.findings_label")}</p>
            <h3>{t("guide.findings_title")}</h3>
            <dl>
              <div><dt>{t("guide.finding_identity")}</dt><dd>Stanford University · ORCID</dd></div>
              <div><dt>{t("guide.finding_coverage")}</dt><dd>593 {lang === "zh" ? "篇论文" : "papers"}</dd></div>
              <div><dt>{t("guide.finding_impact")}</dt><dd>217,104 {lang === "zh" ? "次引用" : "citations"} · h-index 133</dd></div>
            </dl>
            <ul>
              <li><CheckCircle2 />{t("guide.finding_one")}</li>
              <li><CheckCircle2 />{t("guide.finding_two")}</li>
              <li><GitBranch />{t("guide.finding_three")}</li>
            </ul>
            <p className="scholar-case-date">{t("guide.snapshot_note")}</p>
            <Button variant="outline" onClick={onTryExample}>{t("guide.try_example")}<ArrowUpRight /></Button>
          </aside>
        </div>
      </section>

      <section className="scholar-boundaries" aria-labelledby="boundaries-title">
        <div data-scholar-reveal="left">
          <p>{t("guide.boundary_label")}</p>
          <h2 id="boundaries-title">{t("guide.boundary_title")}</h2>
          <span>{t("guide.boundary_description")}</span>
        </div>
        <div className="scholar-boundary-list">
          {[1, 2, 3, 4].map((number) => (
            <article key={number} data-scholar-reveal="right"><CircleAlert /><p>{t(`guide.boundary_${number}`)}</p></article>
          ))}
        </div>
      </section>
    </div>
  )
}
