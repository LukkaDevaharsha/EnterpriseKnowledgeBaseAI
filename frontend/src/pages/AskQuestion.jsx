import BaseAI from '../components/BaseAI'

const EXAMPLES = [
  'What does the leave policy say about annual leave?',
  'Which documents cover employee onboarding?',
  'What is the approval process for expenses?',
]

export default function AskQuestion() {
  return <div className="page-content ask-page">
    <BaseAI fullPage suggestions={EXAMPLES} />
    <p className="privacy-note">Your conversations are saved to your account. Document citations identify passages used for each answer.</p>
  </div>
}
