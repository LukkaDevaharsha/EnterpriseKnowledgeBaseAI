import BaseAI from '../components/BaseAI'

const EXAMPLES = [
  'What does the leave policy say about annual leave?',
  'Which documents cover employee onboarding?',
  'What is the approval process for expenses?',
]

export default function AskQuestion() {
  return <div className="page-content ask-page">
    <header className="page-heading">
      <div><span className="eyebrow">ENTERPRISE KNOWLEDGE ASSISTANT</span>
        <h1>Ask BaseAI</h1>
        <p>Get answers grounded in the sources available to your account.</p>
      </div>
    </header>
    <BaseAI suggestions={EXAMPLES} />
    <p className="privacy-note">Questions are not saved as conversation history. Document citations identify passages used for each answer.</p>
  </div>
}
