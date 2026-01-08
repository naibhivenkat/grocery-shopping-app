package com.example.groceryshoppingapp.adapters

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.network.ShopReview

class ShopReviewsAdapter(
    private val reviews: List<ShopReview>
) : RecyclerView.Adapter<ShopReviewsAdapter.ViewHolder>() {

    inner class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val emoji: TextView = view.findViewById(R.id.txtEmoji)
        val review: TextView = view.findViewById(R.id.txtReview)
        val date: TextView = view.findViewById(R.id.txtDate)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_review, parent, false)
        return ViewHolder(view)
    }

    override fun getItemCount() = reviews.size

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val r = reviews[position]

        holder.emoji.text = r.emoji
        holder.review.text = r.review.ifBlank { "No comment" }

        holder.date.text =
            "${r.customer_name ?: "Customer"} • ${r.created_at}"
    }

}
