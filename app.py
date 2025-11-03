
import os
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, g
from groq import Groq
from dotenv import load_dotenv
import time
import random
import json
from collections import defaultdict
from agent import run_graph_agent
import markdown 

# --- NEW FIREBASE IMPORTS AND INITIALIZATION ---
import firebase_admin
from firebase_admin import credentials, auth, firestore

load_dotenv()

cred = credentials.Certificate("firebase_admin_sdk.json")
firebase_admin.initialize_app(cred)
db = firestore.client() # This gives us a Firestore client to interact with the database later


app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your_secret_key_here')

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

SUBJECTS = ["Logical Reasoning", "Quantitative Aptitude", "Verbal Ability"]
SUBJECT_MAP = {"Logical Reasoning": "LR", "Quantitative Aptitude": "QA", "Verbal Ability": "VA"}

@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    g.user = None
    g.guest_id = session.get('guest_id')

    if user_id:
        try:
            g.user = auth.get_user(user_id)
        except auth.UserNotFoundError:
            session.clear() # User not found in Firebase, clear the session

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if not g.user and not g.guest_id:
            return redirect(url_for('auth_page'))

        quiz_type = request.form.get('quiz_type')
        difficulty = request.form.get('difficulty', 'Medium')

        if quiz_type == 'aptitude':
            selected_subjects = request.form.getlist('subjects')
            num_questions = min(int(request.form.get('num_questions', 5)), 30)
            
            questions = []
            if selected_subjects:
                # ... (the rest of your existing aptitude generation logic is fine here) ...
                questions_per_subject = num_questions // len(selected_subjects)
                remaining_questions = num_questions % len(selected_subjects)
                for i, subject in enumerate(selected_subjects):
                    q_count = questions_per_subject + (1 if i < remaining_questions else 0)
                    if q_count > 0:
                        subject_questions = generate_questions(subject, difficulty, q_count)
                        for q in subject_questions:
                            q['subject'] = subject
                            q.setdefault('chapter', 'General')
                        questions.extend(subject_questions)
            random.shuffle(questions)
            
            session['questions'] = questions
            session['user_answers'] = {}
            # Clear any leftover programming questions
            session.pop('programming_questions', None)
            return redirect(url_for('quiz'))

        elif quiz_type == 'programming':
            programming_topics = request.form.getlist('programming_topics')
            num_dsa = int(request.form.get('num_dsa_questions', 0))
            num_sql = int(request.form.get('num_sql_questions', 0))
            
            programming_questions = []
            
            # Generate DSA questions if the topic was selected and num > 0
            if 'DSA' in programming_topics and num_dsa > 0:
                for _ in range(num_dsa):
                    question = generate_programming_question('DSA', difficulty)
                    programming_questions.append(question)
            
            # Generate SQL questions if the topic was selected and num > 0
            if 'SQL' in programming_topics and num_sql > 0:
                for _ in range(num_sql):
                    question = generate_programming_question('SQL', difficulty)
                    programming_questions.append(question)
            
            if not programming_questions:
                # If user selected programming but didn't check any topics, or set numbers to 0
                # It's better to redirect them back to the start page.
                return redirect(url_for('index'))

            session['programming_questions'] = programming_questions
            # Clear any leftover aptitude questions
            session.pop('questions', None) 
            return redirect(url_for('programming_quiz'))
    
    # GET request logic remains the same
    if g.user or g.guest_id:
        return render_template('index.html', subjects=SUBJECTS)
    return render_template('welcome.html')


# REPLACE the old /programming_quiz placeholder with this CORRECT version
@app.route('/programming_quiz')
def programming_quiz():
    # Check if questions have been generated and stored, otherwise redirect.
    if 'programming_questions' not in session:
        return redirect(url_for('index'))
    
    # Retrieve the questions from the session.
    questions = session.get('programming_questions', [])

    # This is the correct line. It renders the interactive HTML page.
    return render_template('programming_quiz.html', 
                           questions=questions,
                           questions_json=json.dumps(questions))

@app.route('/quiz')
def quiz():
    if 'questions' not in session:
        return redirect(url_for('index'))
    
    all_questions = session.get('questions', [])
    
    time_left = None
    if session.get('timed_test'):
        elapsed = time.time() - session['start_time']
        total_time = len(all_questions) * 60
        time_left = max(0, total_time - elapsed)

    return render_template('quiz.html', 
                           questions=all_questions,
                           total_questions=len(all_questions),
                           timed_test=session.get('timed_test', False),
                           time_left=time_left,
                           subject_map=SUBJECT_MAP)


@app.route('/check_answer', methods=['POST'])
def check_answer():
    if 'questions' not in session:
        return jsonify({'error': 'Session expired'}), 400
    
    data = request.get_json()
    selected_option = data.get('selected_option')
    question_index = data.get('question_index')

    all_questions = session.get('questions', [])
    
    if question_index is None or not (0 <= question_index < len(all_questions)):
        return jsonify({'error': 'Invalid question index'}), 400
        
    question = all_questions[question_index]
    is_correct = (selected_option == question['correct_answer'])
    
    session['user_answers'][str(question_index)] = {
        'user_answer': selected_option,
        'is_correct': is_correct
    }
    
    session.modified = True
    
    return jsonify({
        'is_correct': is_correct,
        'correct_answer': question['correct_answer'],
        'solution': question.get('solution', "Solution not available.")
    })



# NEWEST version - replace the @app.route('/results') function with this
@app.route('/results')
def results():
    if 'questions' not in session:
        return redirect(url_for('index'))

    all_questions = session.get('questions', [])
    user_answers = session.get('user_answers', {})
    
    score = 0
    correct_count = 0
    incorrect_count = 0
    
    topic_breakdown = defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'total': 0})

    for i, q in enumerate(all_questions):
        subject_abbr = SUBJECT_MAP.get(q.get('subject'), 'Unknown')
        topic = f"{subject_abbr} -> {q.get('chapter', 'General')}"
        topic_breakdown[topic]['total'] += 1
        
        answer_info = user_answers.get(str(i))
        if answer_info:
            if answer_info['is_correct']:
                correct_count += 1
                topic_breakdown[topic]['correct'] += 1
            else:
                incorrect_count += 1
                topic_breakdown[topic]['incorrect'] += 1

    score = correct_count
    total = len(all_questions)
    accuracy = (score / total * 100) if total > 0 else 0
    total_time_taken = time.time() - session.get('start_time', 0)

    student_name = g.user.email if g.user else "Guest"

    report_data = {
        'student_name': student_name,
        'score': score,
        'total_questions': total,
        'accuracy': round(accuracy, 2),
        'correct_count': correct_count,
        'incorrect_count': incorrect_count,
        'unanswered_count': total - (correct_count + incorrect_count),
        'total_time_taken': round(total_time_taken),
        'topic_breakdown': {k: dict(v) for k, v in topic_breakdown.items()}
    }

    if g.user:
        try:
            data_to_save = report_data.copy()
            data_to_save['timestamp'] = firestore.SERVER_TIMESTAMP

            # --- THIS IS THE KEY CHANGE ---
            # Old way: db.collection('quiz_results').add(...)
            # New way: Create a document for the user in the 'users' collection,
            # and then add the quiz result to a 'quiz_results' subcollection within that user's document.
            user_doc_ref = db.collection('users').document(g.user.uid)
            user_doc_ref.collection('quiz_results').add(data_to_save)
            
            # We can also set some basic user info on the main user document
            user_doc_ref.set({'email': g.user.email}, merge=True)
            
            print(f"Successfully saved quiz results for user: {g.user.uid}")

        except Exception as e:
            print(f"Error saving to Firestore: {e}")

    session.pop('questions', None)
    session.pop('user_answers', None)
    session.pop('start_time', None)
    session.pop('timed_test', None)

    return render_template('results.html', 
                         score=score, 
                         total=total,
                         report_data_json=json.dumps(report_data))
    
    
    
    
@app.route('/report', methods=['POST'])
def report_page():
    report_data_str = request.form.get('report_data')
    if not report_data_str:
        return "Error: No report data found.", 400
        
    report_data = json.loads(report_data_str)

    # Call our agent to get the report as a Markdown string
    agent_response = run_graph_agent(report_data)
    
    # Convert the Markdown string from the agent into HTML
    report_html = markdown.markdown(agent_response.get("analysis", ""))
    
    # Pass the generated HTML to the template
    return render_template('report.html', 
                           report_data=report_data, 
                           report_html=report_html) # Pass HTML, not text

def generate_questions(subject, difficulty, num_questions):
    subject_instructions = {
        "Logical Reasoning": "Chapters may include: Syllogisms, Blood Relations, Coding-Decoding, Seating Arrangement, Direction Sense.",
        "Quantitative Aptitude": "Chapters may include: Time & Work, Percentages, Profit & Loss, Speed Time & Distance, Ratios.",
        "Verbal Ability": "Chapters may include: Synonyms & Antonyms, Reading Comprehension, Sentence Correction, Para Jumbles, Idioms & Phrases."
    }
    prompt = f"""
    Generate exactly {num_questions} multiple choice questions (MCQ) about {subject} with {difficulty.lower()} difficulty,
    focused on engineering placement scenarios in Indian B.Tech colleges like those asked by companies like Infosys, Wipro, TCS.
    {subject_instructions.get(subject, '')}

    For each question, provide:
    1. The question text.
    2. A specific chapter or topic name for the question (e.g., "Time & Work", "Syllogisms").
    3. Four options labeled A), B), C), D).
    4. The correct answer letter.
    5. A detailed step-by-step solution.

    Format EACH question as a JSON object like this:
    {{
        "chapter": "Chapter Name Here",
        "question": "Question text here",
        "options": {{ "A": "option 1", "B": "option 2", "C": "option 3", "D": "option 4" }},
        "correct_answer": "Correct letter here",
        "solution": "Detailed step-by-step solution here"
    }}

    Return ONLY a JSON array of these questions with the key "questions". Do not include any other text or explanations.
    """
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"},
            temperature=0.7
        )
        response = chat_completion.choices[0].message.content
        questions = json.loads(response).get('questions', [])
        
        if len(questions) < num_questions:
            needed = num_questions - len(questions)
            questions.extend(get_default_questions(subject, needed))
            
        return questions[:num_questions]
    
    except Exception as e:
        return get_default_questions(subject, num_questions)


# ADD THIS NEW FUNCTION right after the generate_questions function
def generate_programming_question(topic, difficulty):
    language_map = {
        "DSA": "a Data Structures and Algorithms (DSA)",
        "SQL": "an SQL"
    }
    topic_instruction = language_map.get(topic, "a generic programming")

    prompt = f"""
    Generate one {difficulty.lower()} difficulty {topic_instruction} problem suitable for a technical interview at a service-based company like TCS or Infosys.

    The response MUST be a single JSON object with the following exact keys:
    - "topic": String (Either "DSA" or "SQL").
    - "title": String (A short, descriptive title for the problem, e.g., "Find the First Non-Repeating Character").
    - "problem_statement": String (A detailed description of the problem. Use Markdown for formatting if needed).
    - "examples": An array of JSON objects. Each object must have "input" and "output" as keys with string values. Provide at least two examples.
    - "constraints": An array of strings listing any constraints (e.g., "1 <= N <= 10^5").

    Example for a DSA question:
    {{
        "topic": "DSA",
        "title": "Two Sum",
        "problem_statement": "Given an array of integers `nums` and an integer `target`, return indices of the two numbers such that they add up to `target`.",
        "examples": [
            {{ "input": "nums = [2, 7, 11, 15], target = 9", "output": "[0, 1]" }},
            {{ "input": "nums = [3, 2, 4], target = 6", "output": "[1, 2]" }}
        ],
        "constraints": [
            "2 <= nums.length <= 10^4",
            "-10^9 <= nums[i] <= 10^9",
            "Only one valid answer exists."
        ]
    }}
    
    Example for an SQL question:
    {{
        "topic": "SQL",
        "title": "Second Highest Salary",
        "problem_statement": "Write a SQL query to fetch the second highest salary from the `Employee` table. If there is no second highest salary, the query should return `null`. The table has two columns: `id` and `salary`.",
        "examples": [
            {{ "input": "Table: [[1, 100], [2, 200], [3, 300]]", "output": "200" }},
            {{ "input": "Table: [[1, 100]]", "output": "null" }}
        ],
        "constraints": [
            "The salary column contains integer values."
        ]
    }}

    Return ONLY the JSON object. Do not include any other text, explanations, or markdown formatting around the JSON.
    """
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"},
            temperature=0.8 # Slightly higher for more creative problems
        )
        response = chat_completion.choices[0].message.content
        # The model should return a single JSON object, so we load it directly
        return json.loads(response)
    
    except Exception as e:
        print(f"Error generating programming question: {e}")
        # Return a default error question if the API fails
        return {
            "topic": topic, "title": "Error Generating Question",
            "problem_statement": "There was an error generating the question from the AI. Please try again.",
            "examples": [], "constraints": []
        }


def get_default_questions(subject, num_questions):
    defaults = {
        "Logical Reasoning": [{"chapter": "Syllogisms", "question": "If all Bloops are Razzies and all Razzies are Lazzies, then all Bloops are definitely Lazzies?", "options": {"A": "True", "B": "False", "C": "Uncertain", "D": "None of the above"}, "correct_answer": "A", "solution": "This is a case of transitive relation. If A implies B and B implies C, then A implies C. So, the statement is True."}],
        "Quantitative Aptitude": [{"chapter": "Speed, Time & Distance", "question": "If a train travels 300 km in 5 hours, what is its average speed?", "options": {"A": "50 km/h", "B": "60 km/h", "C": "70 km/h", "D": "80 km/h"}, "correct_answer": "B", "solution": "Average Speed = Total Distance / Total Time. Speed = 300 km / 5 hours = 60 km/h."}],
        "Verbal Ability": [{"chapter": "Synonyms", "question": "Choose the correct synonym for 'Benevolent'", "options": {"A": "Cruel", "B": "Kind", "C": "Selfish", "D": "Greedy"}, "correct_answer": "B", "solution": "'Benevolent' means well-meaning and kindly. 'Kind' is the closest synonym."}]
    }
    subject_questions = defaults.get(subject, [])
    return subject_questions[:num_questions]



# ADD THIS NEW ROUTE
@app.route('/auth')
def auth_page():
    return render_template('auth.html')



# ... after the get_default_questions function ...

# @app.route('/signup', methods=['GET', 'POST'])
# def signup():
#     if request.method == 'POST':
#         email = request.form.get('email')
#         password = request.form.get('password')
#         try:
#             user = auth.create_user(
#                 email=email,
#                 password=password
#             )
#             session['user_id'] = user.uid # Log the user in immediately
#             return redirect(url_for('index'))
#         except Exception as e:
#             # Handle errors, e.g., email already exists
#             return render_template('signup.html', error=f"Error: {e}")
#     return render_template('signup.html')
# REPLACE the old /signup route with this
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        # Get the role from the hidden input, default to 'student' if not provided
        role = request.form.get('role', 'student') 
        
        try:
            # Step 1: Create the user in Firebase Authentication
            user = auth.create_user(
                email=email,
                password=password
            )

            # Step 2: Create a user document in Firestore with their role
            user_doc_ref = db.collection('users').document(user.uid)
            user_doc_ref.set({
                'email': user.email,
                'role': role  # Use the role from the form
            })
            
            # Step 3: Log the user in and redirect
            session['user_id'] = user.uid
            return redirect(url_for('index'))

        except Exception as e:
            # For a better user experience, we redirect back to the auth page with an error
            # We will need to add logic to auth.html to display this error.
            # For now, this is a simple error handling.
            print(f"Signup Error: {e}")
            return redirect(url_for('auth_page')) # Redirect back to the main auth page

    # If it's a GET request, just show the auth page.
    return redirect(url_for('auth_page'))

# REPLACE the old /login route with this
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        # We are not verifying password on the backend in this simplified flow.
        # A production app should use a more secure method.
        try:
            # Step 1: Get the user from Firebase Auth
            user = auth.get_user_by_email(email)

            # Step 2: Get the user's document from Firestore to check their role
            user_doc_ref = db.collection('users').document(user.uid)
            user_doc = user_doc_ref.get()

            if not user_doc.exists:
                # This case handles users who might exist in Auth but not Firestore
                print("User exists in Auth, but not in Firestore.")
                return redirect(url_for('auth_page'))

            user_role = user_doc.to_dict().get('role')

            # Step 3: Log the user in by setting the session
            session['user_id'] = user.uid

            # Step 4: Redirect based on role
            if user_role == 'teacher':
                return redirect(url_for('teacher_dashboard')) # A new route we will create next
            else: # 'student'
                return redirect(url_for('index'))

        except Exception as e:
            print(f"Login Error: {e}")
            return redirect(url_for('auth_page'))

    # If it's a GET request, just show the auth page.
    return redirect(url_for('auth_page'))

@app.route('/logout')
def logout():
    session.clear() # Clears the entire session, logging out users and guests
    return redirect(url_for('index'))

@app.route('/continue_as_guest', methods=['POST'])
def continue_as_guest():
    session.clear() # Clear any old session
    session['guest_id'] = f"guest_{int(time.time())}" # Create a unique guest ID
    return redirect(url_for('index'))

# We will add the /user_history route in a later step
# NEW functional version - replace the old @app.route('/user_history')
# REPLACE the existing /user_history route with this new version
@app.route('/user_history')
def user_history():
    if not g.user:
        return redirect(url_for('login'))

    results_list = []
    try:
        # Query Firestore, ordering by timestamp ASCENDING so the graph goes from oldest to newest
        docs = db.collection('users').document(g.user.uid).collection('quiz_results').order_by(
            'timestamp', direction=firestore.Query.ASCENDING
        ).stream()

        for doc in docs:
            result_data = doc.to_dict()
            
            # Format the timestamp for display in the list on the left
            if 'timestamp' in result_data and result_data['timestamp']:
                timestamp = result_data['timestamp']
                # Store the original Python datetime object for JS to parse easily
                result_data['timestamp_raw'] = timestamp.isoformat()
                result_data['timestamp'] = timestamp.strftime("%B %d, %Y - %I:%M %p")
            else:
                result_data['timestamp_raw'] = None
                result_data['timestamp'] = "No date available"

            results_list.append(result_data)

    except Exception as e:
        print(f"Error fetching user history: {e}")

    # Pass the results twice: once for the Jinja loop, once as JSON for the JavaScript chart
    return render_template('history.html', 
                           results=results_list, 
                           results_json=json.dumps(results_list, default=str))

# REPLACE the old /teacher_dashboard placeholder with this
@app.route('/teacher_dashboard')
def teacher_dashboard():
    # Security Check 1: Ensure a user is logged in.
    if not g.user:
        return redirect(url_for('auth_page'))
    
    # Security Check 2: Ensure the user's role is 'teacher'.
    user_doc = db.collection('users').document(g.user.uid).get()
    if not user_doc.exists or user_doc.to_dict().get('role') != 'teacher':
        # If they are not a teacher, send them to the student homepage.
        return redirect(url_for('index'))

    # If security checks pass, proceed to fetch student data.
    students_list = []
    try:
        # Query the 'users' collection for all documents where the 'role' field is 'student'
        docs = db.collection('users').where('role', '==', 'student').stream()
        for doc in docs:
            student_data = doc.to_dict()
            student_data['id'] = doc.id  # Add the document ID (user's UID) to the dictionary
            students_list.append(student_data)
    except Exception as e:
        print(f"Error fetching students: {e}")

    return render_template('teacher_dashboard.html', students=students_list)



# REPLACE the existing /student_history/<student_id> route with this FINAL version
@app.route('/student_history/<student_id>')
def view_student_history(student_id):
    # Security Check: Ensure the person viewing is a teacher
    if not g.user:
        return redirect(url_for('auth_page'))
    user_doc_check = db.collection('users').document(g.user.uid).get()
    if not user_doc_check.exists or user_doc_check.to_dict().get('role') != 'teacher':
        return redirect(url_for('index'))

    results_list = []
    student_email = "Student not found"
    try:
        student_doc = db.collection('users').document(student_id).get()
        if student_doc.exists:
            student_email = student_doc.to_dict().get('email', 'N/A')

        # CRITICAL FIX 1: Order by ASCENDING for a correct timeline graph
        docs = db.collection('users').document(student_id).collection('quiz_results').order_by(
            'timestamp', direction=firestore.Query.ASCENDING
        ).stream()

        for doc in docs:
            result_data = doc.to_dict()
            result_data['id'] = doc.id # Needed for the modal button

            if 'timestamp' in result_data and result_data['timestamp']:
                timestamp = result_data['timestamp']
                # CRITICAL FIX 2: Create a universal ISO format for JavaScript
                result_data['timestamp_raw'] = timestamp.isoformat()
                # Create the pretty format for the list display
                result_data['timestamp'] = timestamp.strftime("%B %d, %Y at %I:%M %p")
            else:
                result_data['timestamp_raw'] = None
                result_data['timestamp'] = "No date available"
            
            results_list.append(result_data)

    except Exception as e:
        print(f"Error fetching student history: {e}")

    return render_template('view_student_history.html', 
                           results=results_list, 
                           student_email=student_email,
                           student_id=student_id,
                           results_json=json.dumps(results_list, default=str))
    
# ADD THIS FINAL ROUTE
@app.route('/get_report/<student_id>/<result_id>')
def get_report(student_id, result_id):
    # Security Check: Ensure the person viewing is a teacher
    if not g.user or not db.collection('users').document(g.user.uid).get().to_dict().get('role') == 'teacher':
        return jsonify({"error": "Unauthorized"}), 403

    try:
        # Fetch the specific quiz result document from Firestore
        doc_ref = db.collection('users').document(student_id).collection('quiz_results').document(result_id)
        result_doc = doc_ref.get()

        if not result_doc.exists:
            return jsonify({"error": "Report not found"}), 404

        # The document data is the 'report_data' our agent needs
        report_data = result_doc.to_dict()

        # --- Call our AI agent to generate the analysis ---
        agent_response = run_graph_agent(report_data)
        
        # Convert the Markdown string from the agent into HTML
        report_html = markdown.markdown(agent_response.get("analysis", "Error: Could not generate report."))
        
        return jsonify({"html": report_html})

    except Exception as e:
        print(f"Error getting report: {e}")
        return jsonify({"error": "An internal error occurred."}), 500    


# ADD THIS FINAL ROUTE FOR CODE EVALUATION
@app.route('/evaluate_code', methods=['POST'])
def evaluate_code():
    data = request.get_json()
    question = data.get('question')
    user_code = data.get('user_code')
    language = data.get('language')

    if not all([question, user_code, language]):
        return jsonify({"error": "Missing data for evaluation."}), 400

    prompt = f"""
    Act as an expert programming interview evaluator for a top service-based company.
    Your task is to evaluate a user's code submission for a given problem.
    Provide your feedback in Markdown format.

    **The Problem:**
    - Title: {question['title']}
    - Statement: {question['problem_statement']}

    **The User's Submission:**
    - Language: {language}
    - Code:
    ```
    {user_code}
    ```

    **Your Evaluation:**
    Provide a comprehensive evaluation with the following structure:

    ### 1. Correctness & Logic
    - Does the code solve the problem correctly?
    - Does it pass the example cases?
    - Are there any logical errors or edge cases the user missed?

    ### 2. Efficiency
    - Analyze the time and space complexity of the user's solution.
    - Is it an optimal solution? If not, what would be a more efficient approach?

    ### 3. Code Style & Readability
    - Is the code clean, well-formatted, and easy to understand?
    - Are variable names meaningful?

    ### 4. Optimal Solution
    - After providing the feedback above, present a correct and optimal solution in {language}.
    - Briefly explain why this solution is better.

    Structure your entire response in clear, helpful Markdown.
    """

    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            temperature=0.3 # Lower temperature for more deterministic feedback
        )
        feedback_markdown = chat_completion.choices[0].message.content
        
        # Convert the AI's Markdown response to HTML
        feedback_html = markdown.markdown(feedback_markdown, extensions=['fenced_code'])
        
        return jsonify({"feedback_html": feedback_html})

    except Exception as e:
        print(f"Error during code evaluation: {e}")
        return jsonify({"error": "The AI evaluator is currently unavailable. Please try again later."}), 500

# ADD THIS NEW ROUTE AT THE END OF YOUR APP.PY
@app.route('/quiz_complete')
def quiz_complete():
    # Clear session data related to the programming quiz
    session.pop('programming_questions', None)
    session.pop('programming_topics', None)
    session.pop('difficulty', None)
    return render_template('quiz_complete.html')


if __name__ == '__main__':
    app.run(debug=True)







# import os
# from flask import Flask, render_template, request, jsonify, session, redirect, url_for
# from groq import Groq
# from dotenv import load_dotenv
# import time
# import random
# import json
# from collections import defaultdict

# # --- We will import agent.py here later ---
# from agent import run_graph_agent
# import markdown

# load_dotenv()

# app = Flask(__name__)
# app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your_secret_key_here')

# client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# SUBJECTS = ["Logical Reasoning", "Quantitative Aptitude", "Verbal Ability"]
# SUBJECT_MAP = {
#     "Logical Reasoning": "LR",
#     "Quantitative Aptitude": "QA",
#     "Verbal Ability": "VA"
# }

# @app.route('/', methods=['GET', 'POST'])
# def index():
#     if request.method == 'POST':
#         selected_subjects = request.form.getlist('subjects')
#         difficulty = request.form.get('difficulty', 'Medium')
#         num_questions = min(int(request.form.get('num_questions', 5)), 30)
#         timed_test = request.form.get('timed_test') == 'on'
        
#         questions = []
#         if selected_subjects:
#             questions_per_subject = num_questions // len(selected_subjects)
#             remaining_questions = num_questions % len(selected_subjects)
            
#             for i, subject in enumerate(selected_subjects):
#                 q_count = questions_per_subject + (1 if i < remaining_questions else 0)
#                 if q_count > 0:
#                     subject_questions = generate_questions(subject, difficulty, q_count)
#                     for q_idx, q in enumerate(subject_questions):
#                         q['subject'] = subject
#                         q['id'] = f"{subject}-{i}-{q_idx}" # Unique ID for each question
#                         q.setdefault('chapter', 'General')
#                     questions.extend(subject_questions)
        
#         random.shuffle(questions)
        
#         session['questions'] = questions
#         session['score'] = 0
#         session['start_time'] = time.time()
#         session['timed_test'] = timed_test
        
#         # This will now store the full question object after it's answered
#         session['user_answers'] = {} 
        
#         return redirect(url_for('quiz'))
    
#     return render_template('index.html', subjects=SUBJECTS)

# @app.route('/quiz')
# def quiz():
#     if 'questions' not in session:
#         return redirect(url_for('index'))
    
#     all_questions = session.get('questions', [])
    
#     time_left = None
#     if session.get('timed_test'):
#         elapsed = time.time() - session['start_time']
#         total_time = len(all_questions) * 60 # 60 seconds per question
#         time_left = max(0, total_time - elapsed)

#     # CORRECTION: Pass the Python list/dict directly.
#     # The 'tojson' filter in the template will handle the conversion safely.
#     return render_template('quiz.html', 
#                            questions=all_questions, # Pass the python object
#                            total_questions=len(all_questions),
#                            timed_test=session.get('timed_test', False),
#                            time_left=time_left,
#                            subject_map=SUBJECT_MAP) # Pass the python object


# @app.route('/check_answer', methods=['POST'])
# def check_answer():
#     if 'questions' not in session:
#         return jsonify({'error': 'Session expired'}), 400
    
#     data = request.get_json()
#     selected_option = data.get('selected_option')
#     question_index = data.get('question_index')

#     all_questions = session.get('questions', [])
    
#     if question_index is None or not (0 <= question_index < len(all_questions)):
#         return jsonify({'error': 'Invalid question index'}), 400
        
#     question = all_questions[question_index]
#     is_correct = (selected_option == question['correct_answer'])
    
#     # Store the user's response in the session
#     session['user_answers'][str(question_index)] = {
#         'user_answer': selected_option,
#         'is_correct': is_correct
#     }
    
#     session.modified = True
    
#     return jsonify({
#         'is_correct': is_correct,
#         'correct_answer': question['correct_answer'],
#         'solution': question.get('solution', "Solution not available.")
#     })


# @app.route('/results')
# def results():
#     if 'questions' not in session:
#         return redirect(url_for('index'))

#     all_questions = session.get('questions', [])
#     user_answers = session.get('user_answers', {})
    
#     score = 0
#     correct_count = 0
#     incorrect_count = 0
    
#     topic_breakdown = defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'total': 0})

#     for i, q in enumerate(all_questions):
#         subject_abbr = SUBJECT_MAP.get(q.get('subject'), 'Unknown')
#         topic = f"{subject_abbr} -> {q.get('chapter', 'General')}"
#         topic_breakdown[topic]['total'] += 1
        
#         answer_info = user_answers.get(str(i))
#         if answer_info:
#             if answer_info['is_correct']:
#                 correct_count += 1
#                 topic_breakdown[topic]['correct'] += 1
#             else:
#                 incorrect_count += 1
#                 topic_breakdown[topic]['incorrect'] += 1

#     score = correct_count
#     total = len(all_questions)
#     accuracy = (score / total * 100) if total > 0 else 0
#     total_time_taken = time.time() - session.get('start_time', 0)

#     report_data = {
#         'student_name': 'User',
#         'score': score,
#         'total_questions': total,
#         'accuracy': round(accuracy, 2),
#         'correct_count': correct_count,
#         'incorrect_count': incorrect_count,
#         'unanswered_count': total - (correct_count + incorrect_count),
#         'total_time_taken': round(total_time_taken),
#         'topic_breakdown': dict(topic_breakdown)
#     }

#     session.clear()

#     return render_template('results.html', 
#                          score=score, 
#                          total=total,
#                          report_data_json=json.dumps(report_data))


# @app.route('/report', methods=['POST'])
# def report_page():
#     report_data_str = request.form.get('report_data')
#     if not report_data_str:
#         return "Error: No report data found.", 400
        
#     report_data = json.loads(report_data_str)

#     # This is the magic moment! We call our agent with the data.
#     agent_response = run_graph_agent(report_data)
    
#     # Convert the Markdown response from the agent into HTML
#     report_html = markdown.markdown(agent_response.get("analysis", ""))
    
#     return render_template('report.html', 
#                            report_data=report_data, 
#                            report_html=report_html)

# # --- The generate_questions and get_default_questions functions remain unchanged ---
# def generate_questions(subject, difficulty, num_questions):
#     # (This function is the same as in the previous step, no changes needed)
#     subject_instructions = {
#         "Logical Reasoning": "Chapters may include: Syllogisms, Blood Relations, Coding-Decoding, Seating Arrangement, Direction Sense.",
#         "Quantitative Aptitude": "Chapters may include: Time & Work, Percentages, Profit & Loss, Speed Time & Distance, Ratios.",
#         "Verbal Ability": "Chapters may include: Synonyms & Antonyms, Reading Comprehension, Sentence Correction, Para Jumbles, Idioms & Phrases."
#     }
#     prompt = f"""
#     Generate exactly {num_questions} multiple choice questions (MCQ) about {subject} with {difficulty.lower()} difficulty,
#     focused on engineering placement scenarios in Indian B.Tech colleges like those asked by companies like Infosys, Wipro, TCS.
#     {subject_instructions.get(subject, '')}

#     For each question, provide:
#     1. The question text.
#     2. A specific chapter or topic name for the question (e.g., "Time & Work", "Syllogisms").
#     3. Four options labeled A), B), C), D).
#     4. The correct answer letter.
#     5. A detailed step-by-step solution.

#     Format EACH question as a JSON object like this:
#     {{
#         "chapter": "Chapter Name Here",
#         "question": "Question text here",
#         "options": {{ "A": "option 1", "B": "option 2", "C": "option 3", "D": "option 4" }},
#         "correct_answer": "Correct letter here",
#         "solution": "Detailed step-by-step solution here"
#     }}

#     Return ONLY a JSON array of these questions with the key "questions". Do not include any other text or explanations.
#     """
#     try:
#         chat_completion = client.chat.completions.create(
#             messages=[{"role": "user", "content": prompt}],
#             model="llama3-8b-8192",
#             response_format={"type": "json_object"},
#             temperature=0.7
#         )
#         response = chat_completion.choices[0].message.content
#         questions = json.loads(response).get('questions', [])
        
#         if len(questions) < num_questions:
#             needed = num_questions - len(questions)
#             questions.extend(get_default_questions(subject, needed))
            
#         return questions[:num_questions]
    
#     except Exception as e:
#         return get_default_questions(subject, num_questions)

# def get_default_questions(subject, num_questions):
#     # (This function is the same as in the previous step, no changes needed)
#     defaults = {
#         "Logical Reasoning": [{"chapter": "Syllogisms", "question": "If all Bloops are Razzies and all Razzies are Lazzies, then all Bloops are definitely Lazzies?", "options": {"A": "True", "B": "False", "C": "Uncertain", "D": "None of the above"}, "correct_answer": "A", "solution": "This is a case of transitive relation. If A implies B and B implies C, then A implies C. So, the statement is True."}],
#         "Quantitative Aptitude": [{"chapter": "Speed, Time & Distance", "question": "If a train travels 300 km in 5 hours, what is its average speed?", "options": {"A": "50 km/h", "B": "60 km/h", "C": "70 km/h", "D": "80 km/h"}, "correct_answer": "B", "solution": "Average Speed = Total Distance / Total Time. Speed = 300 km / 5 hours = 60 km/h."}],
#         "Verbal Ability": [{"chapter": "Synonyms", "question": "Choose the correct synonym for 'Benevolent'", "options": {"A": "Cruel", "B": "Kind", "C": "Selfish", "D": "Greedy"}, "correct_answer": "B", "solution": "'Benevolent' means well-meaning and kindly. 'Kind' is the closest synonym."}]
#     }
#     subject_questions = defaults.get(subject, [])
#     return subject_questions[:num_questions]


# if __name__ == '__main__':
#     app.run(debug=True)

