import { BrowserRouter } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import { LanguageProvider } from "./i18n/LanguageProvider";
import { AppRoutes } from "./routes/AppRoutes";

function App() {
  return (
    <LanguageProvider>
      <AuthProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </AuthProvider>
    </LanguageProvider>
  );
}

export default App;
