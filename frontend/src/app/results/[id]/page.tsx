import ResultsClient from "./ResultsClient";

interface ResultsPageProps {
  params: { id: string };
}

export default function ResultsPage({ params }: ResultsPageProps) {
  return <ResultsClient jobId={params.id} />;
}
