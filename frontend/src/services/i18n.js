// UI strings — English / Arabic. The toggle in the header switches the whole
// shell (and flips the document to RTL); the backend is told the language per
// query so the agents answer in Arabic too.

const STR = {
  appTitle: { en: 'SAS Agentic AI Copilot', ar: 'المساعد الذكي الوكيل' },
  connecting: { en: 'Connecting…', ar: 'جارٍ الاتصال…' },
  connected: { en: 'Connected', ar: 'متصل' },
  notConfigured: { en: 'Not configured', ar: 'غير مُهيّأ' },
  backendOffline: { en: 'Backend offline', ar: 'الخادم غير متصل' },
  langButton: { en: 'عربي', ar: 'English' },

  recentConversations: { en: 'Recent conversations', ar: 'المحادثات الأخيرة' },
  newConversation: { en: '+ New conversation', ar: '+ محادثة جديدة' },
  newConversationTitle: { en: 'New conversation', ar: 'محادثة جديدة' },
  suggestedPrompts: { en: 'Suggested prompts', ar: 'أسئلة مقترحة' },
  rename: { en: 'Rename', ar: 'إعادة تسمية' },
  delete: { en: 'Delete', ar: 'حذف' },

  welcome: {
    en: 'Welcome to the SAS Agentic AI Copilot. Pick an agent from the dropdown above — the SAS Viya Copilot, the Investigation Assistant, the Procurement Integrity Analyst, or Global Intelligence — and ask away.',
    ar: 'مرحباً بك في المساعد الذكي الوكيل من SAS. اختر وكيلاً من القائمة أعلاه — مساعد SAS Viya، مساعد التحقيقات، محلّل نزاهة المشتريات، أو الاستخبارات العالمية — واسأل ما تشاء.',
  },

  selectAgent: { en: 'Select an agent', ar: 'اختر وكيلاً' },
  serviceUnreachable: { en: 'Service unreachable', ar: 'تعذّر الوصول إلى الخدمة' },
  agents: { en: 'Agents', ar: 'الوكلاء' },
  collections: { en: 'Collections', ar: 'المجموعات' },
  noAgents: { en: 'No agents available on this deployment.', ar: 'لا يوجد وكلاء متاحون في هذا النشر.' },

  selectAgentFirst: { en: 'Select an agent from the dropdown first.', ar: 'اختر وكيلاً من القائمة أولاً.' },
  askAnything: { en: 'Ask {name} anything…', ar: 'اسأل {name} أي شيء…' },
  selectThenAsk: { en: 'Select an agent above, then ask anything…', ar: 'اختر وكيلاً من الأعلى ثم اسأل أي شيء…' },
  attachTooltip: {
    en: 'Attach a document (PDF, DOCX, TXT, CSV…) — its text is sent with your question',
    ar: 'أرفق مستنداً (PDF، DOCX، TXT، CSV…) — يُرسل نصه مع سؤالك',
  },
  speakTooltip: { en: 'Speak instead of typing', ar: 'تحدّث بدلاً من الكتابة' },
  readingDocument: { en: 'Reading document…', ar: 'جارٍ قراءة المستند…' },
  sentWithNext: { en: '· sent with your next question', ar: '· يُرسل مع سؤالك التالي' },
  firstKChars: { en: 'first {n}k chars', ar: 'أول {n} ألف حرف' },
  kChars: { en: '{n}k chars', ar: '{n} ألف حرف' },
  stepsSoFar: { en: '{n} step{s} so far', ar: '{n} خطوة حتى الآن' },
  agentTimeout: {
    en: 'The agent did not answer within {n}s — the query may still be running on the server.',
    ar: 'لم يُجب الوكيل خلال {n} ثانية — قد يكون الاستعلام لا يزال قيد التنفيذ على الخادم.',
  },
  agentErrorPrefix: { en: 'Agent error:', ar: 'خطأ من الوكيل:' },
  errorPrefix: { en: 'Error:', ar: 'خطأ:' },

  toolCallsHeader: { en: 'Agent tool calls · {n} step{s}', ar: 'استدعاءات أدوات الوكيل · {n} خطوة' },

  openInVA: { en: 'Open in SAS Visual Analytics ↗', ar: 'فتح في SAS Visual Analytics ↗' },
  clickToZoom: { en: 'Click to enlarge', ar: 'انقر للتكبير' },

  queryDetails: { en: 'Query details', ar: 'تفاصيل الاستعلام' },
  loadingTrace: { en: 'loading trace…', ar: 'جارٍ تحميل الأثر…' },
  inputPrompt: { en: 'Input prompt', ar: 'نص السؤال' },
  toolCallsSection: { en: 'Tool calls', ar: 'استدعاءات الأدوات' },
  noToolCalls: { en: 'No tool calls recorded for this query.', ar: 'لا توجد استدعاءات أدوات مسجّلة لهذا الاستعلام.' },
  retrievalSection: { en: 'Retrieval calls (RAG)', ar: 'استدعاءات الاسترجاع (RAG)' },
  noRetrieval: { en: 'No retrieval calls recorded for this query.', ar: 'لا توجد استدعاءات استرجاع مسجّلة لهذا الاستعلام.' },
  llmSection: { en: 'LLM calls', ar: 'استدعاءات النموذج اللغوي' },
  noLlm: { en: 'No LLM calls recorded for this query.', ar: 'لا توجد استدعاءات نموذج لغوي مسجّلة لهذا الاستعلام.' },
  contextSection: { en: 'Retrieved context', ar: 'السياق المسترجَع' },
  noContext: { en: 'No context passages attached to this answer.', ar: 'لا توجد مقاطع سياق مرفقة بهذه الإجابة.' },
  inputLabel: { en: 'Input', ar: 'المدخلات' },
  outputLabel: { en: 'Output', ar: 'المخرجات' },
  promptLabel: { en: 'Prompt', ar: 'الموجّه' },
  responseLabel: { en: 'Response', ar: 'الاستجابة' },
  open: { en: 'open ↗', ar: 'فتح ↗' },
  tokens: { en: 'tokens', ar: 'رمز' },
  promptCompletion: { en: '{p} prompt · {c} completion', ar: '{p} إدخال · {c} إخراج' },
};

export function translate(lang, key, vars) {
  const entry = STR[key];
  let s = (entry && (entry[lang] ?? entry.en)) ?? key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, v);
  }
  return s;
}
