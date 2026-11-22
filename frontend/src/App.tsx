import { useI18n } from "./i18n";

export function App() {
  const { t, lang, setLang } = useI18n();
  return (
    <main>
      <h1>{t("app.title")}</h1>
      <p>{t("app.placeholder")}</p>
      <button onClick={() => setLang(lang === "zh" ? "en" : "zh")}>{t(lang === "zh" ? "lang.en" : "lang.zh")}</button>
    </main>
  );
}
