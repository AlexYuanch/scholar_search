import { useState } from "react"
import {
  ArrowUpRight,
  BookMarked,
  CheckCircle2,
  CircleAlert,
  GitBranch,
  ScanSearch,
  SearchCheck,
  Sparkles,
} from "lucide-react"
import candidateImage from "@/assets/guide/scholar-case-candidate.png"
import collaborationImage from "@/assets/guide/scholar-case-collaboration.png"
import overviewImage from "@/assets/guide/scholar-case-overview.png"
import workflowImage from "@/assets/guide/scholar-case-workflow.png"
import { Button } from "@/components/ui/button"
import type { Lang } from "@/i18n"

interface Props {
  lang: Lang
  onTryExample: () => void
  t: (key: string) => string
}

const caseImages = {
  candidate: candidateImage,
  workflow: workflowImage,
  overview: overviewImage,
  collaboration: collaborationImage,
}

type CaseKey = keyof typeof caseImages

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
              <div>
                <Icon />
                <span>0{index + 1}</span>
              </div>
              <h3>{title}</h3>
              <p>{text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="scholar-case-study" aria-labelledby="case-study-title">
        <div className="scholar-case-intro" data-scholar-reveal="up">
          <div>
            <p>{t("guide.case_label")}</p>
            <h2 id="case-study-title">{t("guide.case_title")}</h2>
          </div>
          <p>{t("guide.case_description")}</p>
        </div>

        <div className="scholar-case-layout">
          <div className="scholar-case-viewer" data-scholar-reveal="left">
            <div className="scholar-case-tabs" role="tablist" aria-label={t("guide.case_title")}>
              {cases.map((item) => (
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeCase === item.key}
                  key={item.key}
                  onClick={() => setActiveCase(item.key)}
                >
                  {item.title}
                </button>
              ))}
            </div>
            <div className="scholar-case-screen">
              <img
                key={active.key}
                src={caseImages[active.key]}
                alt={`${t("guide.case_title")} · ${active.title}`}
              />
            </div>
            <div className="scholar-case-caption">
              <strong>{active.title}</strong>
              <span>{active.text}</span>
            </div>
          </div>

          <aside className="scholar-case-findings" data-scholar-reveal="right">
            <p className="scholar-case-kicker">
              <Sparkles />
              {t("guide.findings_label")}
            </p>
            <h3>{t("guide.findings_title")}</h3>
            <dl>
              <div>
                <dt>{t("guide.finding_identity")}</dt>
                <dd>Stanford University · ORCID</dd>
              </div>
              <div>
                <dt>{t("guide.finding_coverage")}</dt>
                <dd>593 {lang === "zh" ? "篇论文" : "papers"}</dd>
              </div>
              <div>
                <dt>{t("guide.finding_impact")}</dt>
                <dd>217,104 {lang === "zh" ? "次引用" : "citations"} · h-index 133</dd>
              </div>
            </dl>
            <ul>
              <li><CheckCircle2 />{t("guide.finding_one")}</li>
              <li><CheckCircle2 />{t("guide.finding_two")}</li>
              <li><GitBranch />{t("guide.finding_three")}</li>
            </ul>
            <p className="scholar-case-date">{t("guide.snapshot_note")}</p>
            <Button variant="outline" onClick={onTryExample}>
              {t("guide.try_example")}<ArrowUpRight />
            </Button>
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
            <article key={number} data-scholar-reveal="right">
              <CircleAlert />
              <p>{t(`guide.boundary_${number}`)}</p>
            </article>
          ))}
        </div>
      </section>
    </div>
  )
}
