import BaseAI from '../components/BaseAI'
import { useAuth } from '../context/useAuth'

const EXAMPLES = [
  'What does the leave policy say about annual leave?',
  'Which documents cover employee onboarding?',
  'What is the approval process for expenses?',
]

export default function AskQuestion() {
  const { user } = useAuth()
  const adminMode = user?.role === 'ADMIN'
  return <div className="page-content ask-page">
    <BaseAI fullPage suggestions={adminMode ? ['What is machine learning?', 'How does photosynthesis work?', 'Explain the water cycle.'] : EXAMPLES} />
    <p className="privacy-note">{adminMode
      ? 'Administrator BaseAI answers general knowledge questions only. It does not search user documents or return document citations.'
      : 'Your conversations are saved to your account. Document citations identify passages used for each answer.'}</p>
  </div>
}
