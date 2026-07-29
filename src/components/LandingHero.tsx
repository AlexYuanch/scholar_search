import { useEffect } from "react"
import { ArrowRight, BookOpen, Network, Search, ShieldCheck } from "lucide-react"
import researchAssistantDark from "@/assets/research-assistant.jpg"
import researchAssistantLight from "@/assets/research-assistant-light.jpg"
import LandingGuide from "@/components/LandingGuide"
import { Button } from "@/components/ui/button"
import type { Lang } from "@/i18n"

interface Props {
  query: string
  loading: boolean
  dark: boolean
  lang: Lang
  onQueryChange: (value: string) => void
  onSearch: () => void
  t: (key: string) => string
}

export default function LandingHero({
  query,
  loading,
  dark,
  lang,
  onQueryChange,
  onSearch,
  t,
}: Props) {
  useEffect(() => {
    const items = Array.from(
      document.querySelectorAll<HTMLElement>(".scholar-landing [data-scholar-reveal]"),
    )
    if (!items.length) return

    if (!("IntersectionObserver" in window)) {
      items.forEach((item) => item.classList.add("is-visible"))
      return
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          entry.target.classList.toggle("is-visible", entry.isIntersecting)
        })
      },
      {
        threshold: 0.08,
        rootMargin: "-5% 0px -8%",
      },
    )
    items.forEach((item) => observer.observe(item))
    return () => observer.disconnect()
  }, [])

  const abilities = [
    {
      icon: BookOpen,
      number: "01",
      title: t("landing.identity_title"),
      text: t("landing.identity_desc"),
      tags: lang === "zh" ? ["研究方向", "代表作", "时间线"] : ["Topics", "Key work", "Timeline"],
    },
    {
      icon: Network,
      number: "02",
      title: t("landing.research_title"),
      text: t("landing.research_desc"),
      tags: lang === "zh" ? ["合作网络", "共同论文"] : ["Network", "Shared papers"],
    },
    {
      icon: ShieldCheck,
      number: "03",
      title: t("landing.network_title"),
      text: t("landing.network_desc"),
      tags: lang === "zh" ? ["近期进展", "方向变化"] : ["Recent work", "Direction shifts"],
    },
  ]

  return (
    <section className="scholar-landing">
      <div className="scholar-hero">
        <div className="scholar-hero-copy">
          <p className="scholar-eyebrow">
            <span />
            {t("landing.eyebrow")}
          </p>
          <h1>
            <span>{t("landing.hero_line_one")}</span>
            <strong>{t("landing.hero_line_two")}</strong>
          </h1>
          <p className="scholar-hero-lead">{t("app.subtitle")}</p>

          <form
            className="scholar-hero-search"
            onSubmit={(event) => {
              event.preventDefault()
              onSearch()
            }}
          >
            <Search aria-hidden="true" />
            <label className="sr-only" htmlFor="landing-scholar-search">
              {t("search.placeholder")}
            </label>
            <input
              id="landing-scholar-search"
              type="text"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder={t("search.placeholder")}
            />
            <Button type="submit" size="lg" disabled={!query.trim()}>
              {loading ? t("search.loading") : t("landing.search_action")}
              <ArrowRight />
            </Button>
          </form>

          <div className="scholar-hero-notes" aria-label={t("landing.trust_note")}>
            <span>{t("landing.note_sources")}</span>
            <span>{t("landing.note_analysis")}</span>
            <span>{t("landing.note_login")}</span>
          </div>
        </div>

        <div className="scholar-hero-visual" aria-label={t("landing.visual_alt")}>
          <div className="scholar-orbit scholar-orbit-one" />
          <div className="scholar-orbit scholar-orbit-two" />
          <span className="scholar-orbit-dot scholar-orbit-dot-one" />
          <span className="scholar-orbit-dot scholar-orbit-dot-two" />
          <span className="scholar-orbit-dot scholar-orbit-dot-three" />
          <div className="scholar-visual-label scholar-visual-label-left">
            <strong>172</strong>
            <span>{lang === "zh" ? "篇论文" : "papers"}</span>
          </div>
          <div className="scholar-visual-label scholar-visual-label-right">
            <strong>56</strong>
            <span>{lang === "zh" ? "位合作者" : "collaborators"}</span>
          </div>
          <img
            className={`scholar-hero-image scholar-hero-image-light ${dark ? "" : "is-visible"}`}
            src={researchAssistantLight}
            alt={dark ? "" : t("landing.visual_alt")}
            aria-hidden={dark}
          />
          <img
            className={`scholar-hero-image scholar-hero-image-dark ${dark ? "is-visible" : ""}`}
            src={researchAssistantDark}
            alt={dark ? t("landing.visual_alt") : ""}
            aria-hidden={!dark}
          />
          <div className="scholar-visual-caption">
            <span>Research map</span>
            <strong>{t("landing.visual_caption")}</strong>
          </div>
        </div>
      </div>

      <div className="scholar-source-strip" data-scholar-reveal="fade">
        <div>
          <p>{t("landing.not_just_search")}</p>
          <div className="scholar-source-list" aria-label={t("landing.trust_note")}>
            <span>OpenAlex</span>
            <span>Crossref</span>
            <span>ORCID</span>
            <span>DeepSeek Agents</span>
          </div>
          <small>{t("landing.source_note")}</small>
        </div>
      </div>

      <div className="scholar-abilities">
        <div className="scholar-section-heading" data-scholar-reveal="up">
          <div>
            <p>{t("landing.workflow_label")}</p>
            <h2>{t("landing.workflow_title")}</h2>
          </div>
          <span>{t("landing.workflow_desc")}</span>
        </div>
        <div className="scholar-ability-grid">
          {abilities.map(({ icon: Icon, number, title, text, tags }) => (
            <article key={number} className="scholar-ability-card" data-scholar-reveal="up">
              <div className="scholar-ability-card-top">
                <Icon />
                <span>{number}</span>
              </div>
              <h3>{title}</h3>
              <p>{text}</p>
              <div>
                {tags.map((tag) => <span key={tag}>{tag}</span>)}
              </div>
            </article>
          ))}
        </div>
      </div>

      <LandingGuide
        lang={lang}
        t={t}
        onTryExample={() => {
          onQueryChange("Fei-Fei Li")
          window.scrollTo({ top: 0, behavior: "smooth" })
          window.setTimeout(() => document.getElementById("landing-scholar-search")?.focus(), 420)
        }}
      />
    </section>
  )
}
