# LLM-Powered TestGen 🚀

An intelligent, full-stack web application designed to generate dynamic aptitude (MCQ) and programming (DSA/SQL) tests with real-time, AI-powered evaluation and personalized feedback. This platform moves beyond static question banks to provide a limitless, adaptive practice environment for students and a comprehensive analytics dashboard for teachers.

---

## 🌟 About The Project

Traditional test preparation platforms rely on finite, static question banks, leading to repetitive practice and a limited scope for skill development. **LLM-Powered TestGen** solves this problem by leveraging modern Large Language Models (LLMs) to create a truly dynamic and intelligent learning ecosystem.

The application serves two primary roles:
- **For Students:** It offers an infinite stream of unique quiz questions for both aptitude and programming. More importantly, it provides an AI-powered agent that acts as a personal tutor, analyzing performance, evaluating code, and recommending targeted learning resources.
- **For Teachers:** It provides a centralized dashboard to monitor student progress, view detailed performance histories, and gain insights into the specific areas where students are struggling.

This project demonstrates a practical, end-to-end implementation of agentic AI systems in a real-world educational context.

---

## ✨ Key Features

- **Dynamic Quiz Generation:** AI-generated Aptitude (MCQ) and Programming (DSA/SQL) questions based on user-selected topics and difficulty.
- **Role-Based Access Control:** Secure user authentication and distinct dashboards for **Students** and **Teachers** using Firebase.
- **Interactive Code Editor:** A full-featured in-browser IDE powered by **CodeMirror** for solving DSA/SQL problems in Python, C++, and Java.
- **AI Code Evaluation:** An expert AI agent that provides detailed feedback on user-submitted code, analyzing its correctness, efficiency (time/space complexity), and style.
- **Agentic Feedback Reports:** An AI agent built with **LangGraph** that analyzes MCQ test results to identify weaknesses and autonomously searches for relevant video tutorials and practice materials.
- **Student Performance Analytics:** A personal dashboard for students to track their quiz history and visualize their accuracy trends over time with **Chart.js**.
- **Teacher Analytics Dashboard:** A comprehensive view for teachers to monitor all registered students and dive deep into their individual performance histories and AI-generated reports.

---

## 🛠️ Tech Stack

| Category          | Technologies                                                                          |
| ----------------- | ------------------------------------------------------------------------------------- |
| **Frontend**      | HTML5, CSS3, Tailwind CSS, JavaScript, CodeMirror.js, Chart.js                          |
| **Backend**       | Python, Flask                                                                         |
| **AI / LLM**      | Groq API (Llama 3.1), LangChain, LangGraph, Tavily Search                             |
| **Database & Auth** | Google Firebase (Authentication & Cloud Firestore)                                    |
| **Deployment**    | Render                                                                               |

---

## ⚙️ Getting Started

Follow these steps to get a local copy up and running.

### Prerequisites

- Python 3.9+
- A Google Firebase project
- API keys from Groq and Tavily

### Local Setup

1.  **Clone the repository:**
    ```sh
    git clone https://github.com/your-username/LLM-powered-testgen.git
    cd LLM-powered-testgen
    ```

2.  **Create a virtual environment and activate it:**
    ```sh
    # For Windows
    python -m venv venv
    .\venv\Scripts\activate

    # For macOS/Linux
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install the required packages:**
    ```sh
    pip install -r requirements.txt
    ```

4.  **Set up Environment Variables:**
    - Create a file named `.env` in the root directory.
    - Add your API keys to this file:
      ```env
      GROQ_API_KEY="your_groq_api_key_here"
      TAVILY_API_KEY="your_tavily_api_key_here"
      FLASK_SECRET_KEY="a_long_random_string_for_session_security"
      ```

5.  **Set up Firebase Credentials:**
    - From your Firebase project console, go to `Project settings` > `Service accounts`.
    - Click "Generate new private key" to download a JSON file.
    - Rename this file to `firebase_admin_sdk.json` and place it in the root directory of the project.
    - **Important:** Ensure this file is listed in your `.gitignore` file to keep your credentials secure.

6.  **Run the application:**
    ```sh
    flask run
    ```
    The application will be available at `http://127.0.0.1:5000`.

---

## 🚀 Deployment on Render

This application is configured for easy deployment on Render.

1.  **Commit your code** to a GitHub repository.
2.  On Render, create a new "Web Service" and connect it to your repository.
3.  Set the **Start Command** to `gunicorn app:app`.
4.  Go to the **"Environment"** tab and add all the secret keys from your `.env` file (`GROQ_API_KEY`, `TAVILY_API_KEY`, `FLASK_SECRET_KEY`).
5.  **For Firebase credentials**, add a new environment variable with the `Key` as `FIREBASE_CREDS`. For the `Value`, paste the **entire content** of your `firebase_admin_sdk.json` file. The application is coded to automatically use this environment variable when deployed.

---

## 🔮 Future Scope

-   **Develop an Adaptive Difficulty Engine:** Implement a system where the difficulty of subsequent questions automatically adjusts based on the user's real-time performance.
-   **Publish a Research Paper:** Conduct a formal comparative analysis of different LLMs (e.g., Llama, GPT-4, Gemini) to evaluate their effectiveness in generating high-quality test questions and pedagogical feedback, with the goal of publishing the findings.
-   **AI-Powered Mock Interview:** Add a feature where a conversational AI acts as an interviewer, asking follow-up questions about the user's submitted code.



---


Project Link: [[https://github.com/your-username/LLM-powered-testgen](https://llm-powered-testgen.onrender.com/)]
